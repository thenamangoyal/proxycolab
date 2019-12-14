import apt, apt.debfile
import pathlib, stat, shutil, urllib.request, subprocess, getpass, time
import secrets, json, re, sys
import IPython.utils.io
import os, tarfile


def _log(message):
    print('[%s] %s' % (time.strftime('%H:%M:%S', time.localtime()), message))


def _installPkg(cache, name):
  pkg = cache[name]
  if pkg.is_installed:
    pass
  else:
    pkg.mark_install()

def _installPkgs(cache, *args):
  for i in args:
    _installPkg(cache, i)

def _download(url, path):
  try:
    with urllib.request.urlopen(url) as response:
      with open(path, 'wb') as outfile:
        shutil.copyfileobj(response, outfile)
  except:
    print("Failed to download ", url)
    raise

def _get_gpu_name():
  r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], stdout = subprocess.PIPE, universal_newlines = True)
  if r.returncode != 0:
    return None
  return r.stdout.strip()

def _check_gpu_available():
  gpu_name = _get_gpu_name()
  if gpu_name == None:
    print("This is not a runtime with GPU")
  else:
    _log('Detected GPU: %s' % gpu_name)
    return True

  return IPython.utils.io.ask_yes_no("Do you want to continue? [y/n]")

def _setupSSHDImpl(ngrok_token, ngrok_region):
  _log('Updating packages...')
  cache = apt.Cache()
  cache.update()
  cache.open(None)
  cache.upgrade()
  cache.commit()

  _log('Unminimizing server...')
  subprocess.run(["unminimize"], input = "y\n", check = True, universal_newlines = True)

  _log('Downloading and installing ngrok...')
  _download("https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-linux-amd64.zip", "ngrok.zip")
  shutil.unpack_archive("ngrok.zip")
  pathlib.Path("ngrok").chmod(stat.S_IXUSR)

  root_password = secrets.token_urlsafe()
  user_password = secrets.token_urlsafe()
  user_name = "colab"
  #print("✂️"*24)
  #print(f"root password: {root_password}")
  #print(f"{user_name} password: {user_password}")
  #print("✂️"*24)
  subprocess.run(["useradd", "-s", "/bin/bash", "-m", user_name])
  subprocess.run(["adduser", user_name, "sudo"], check = True)
  #subprocess.run(["chpasswd"], input = f"root:{root_password}", universal_newlines = True)
  #subprocess.run(["chpasswd"], input = f"{user_name}:{user_password}", universal_newlines = True)


  with open('/etc/sudoers', 'a') as f:
    f.write('\n%s ALL=(ALL) NOPASSWD: ALL' % user_name)
    f.close()

  if not pathlib.Path('/root/.ngrok2/ngrok.yml').exists():
    subprocess.run(["./ngrok", "authtoken", ngrok_token])

  _log('Creating ngrok tunnel...')
  ngrok_proc = subprocess.Popen(["./ngrok", "tcp", "-region", ngrok_region, "1080"])
  time.sleep(2)
  if ngrok_proc.poll() != None:
    raise RuntimeError("Failed to run ngrok. Return code:" + str(ngrok_proc.returncode) + "\nSee runtime log for more info.")

  with urllib.request.urlopen("http://localhost:4040/api/tunnels") as response:
    url = json.load(response)['tunnels'][0]['public_url']
    if url.startswith("tcp://"):
      url = url[len("tcp://"):]

  #_log('Setting up noVNC...')
  #subprocess.run(['git', 'clone', 'https://github.com/novnc/noVNC.git'])
  #subprocess.Popen(['noVNC/utils/launch.sh', '--vnc', 'localhost:5901'])

  return url


def setupSSHD(ngrok_region=None, ngrok_token=None, check_gpu_available=False):
  #if check_gpu_available and not _check_gpu_available():
  #  return False


  if not ngrok_token:
    print("Copy&paste your tunnel authtoken from https://dashboard.ngrok.com/auth")
    print("(You need to sign up for ngrok and login,)")
    ngrok_token = getpass.getpass()

  if not ngrok_region:
    print("Select your ngrok region:")
    print("us - United States (Ohio)")
    print("eu - Europe (Frankfurt)")
    print("ap - Asia/Pacific (Singapore)")
    print("au - Australia (Sydney)")
    print("sa - South America (Sao Paulo)")
    print("jp - Japan (Tokyo)")
    print("in - India (Mumbai)")
    ngrok_region = region = input()

  url = _setupSSHDImpl(ngrok_token, ngrok_region)
  return url

def _setup_nvidia_gl():
  # Install TESLA DRIVER FOR LINUX X64.
  # Kernel module in this driver is already loaded and cannot be neither removed nor updated.
  # (nvidia, nvidia_uvm, nvidia_drm. See dmesg)
  # Version number of nvidia driver for Xorg must match version number of these kernel module.
  # But existing nvidia driver for Xorg might not match.
  # So overwrite them with the nvidia driver that is same version to loaded kernel module.
  ret = subprocess.run(
                  ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                  stdout = subprocess.PIPE,
                  check = True,
                  universal_newlines = True)
  nvidia_version = ret.stdout.strip()
  nvidia_url = "https://us.download.nvidia.com/tesla/{0}/NVIDIA-Linux-x86_64-{0}.run".format(nvidia_version)
  _download(nvidia_url, "nvidia.run")
  pathlib.Path("nvidia.run").chmod(stat.S_IXUSR)
  subprocess.run(["./nvidia.run", "--no-kernel-module", "--ui=none"], input = "1\n", check = True, universal_newlines = True)

  #https://virtualgl.org/Documentation/HeadlessNV
  subprocess.run(["nvidia-xconfig",
                  "-a",
                  "--allow-empty-initial-configuration",
                  "--virtual=1920x1200",
                  "--busid", "PCI:0:4:0"],
                 check = True
                )

  with open("/etc/X11/xorg.conf", "r") as f:
    conf = f.read()
    conf = re.sub('(Section "Device".*?)(EndSection)',
                  '\\1    MatchSeat      "seat-1"\n\\2',
                  conf,
                  1,
                  re.DOTALL)
  #  conf = conf + """
  #Section "Files"
  #    ModulePath "/usr/lib/xorg/modules"
  #    ModulePath "/usr/lib/x86_64-linux-gnu/nvidia-418/xorg/"
  #EndSection
  #"""

  with open("/etc/X11/xorg.conf", "w") as f:
    f.write(conf)

  #!service lightdm stop
  subprocess.run(["/opt/VirtualGL/bin/vglserver_config", "-config", "+s", "+f"], check = True)
  #user_name = "colab"
  #!usermod -a -G vglusers $user_name
  #!service lightdm start

  # Run Xorg server
  # VirtualGL and OpenGL application require Xorg running with nvidia driver to get Hardware 3D Acceleration.
  #
  # Without "-seat seat-1" option, Xorg try to open /dev/tty0 but it doesn't exists.
  # You can create /dev/tty0 with "mknod /dev/tty0 c 4 0" but you will get permision denied error.
  subprocess.Popen(["Xorg", "-seat", "seat-1", "-allowMouseOpenFail", "-novtswitch", "-nolisten", "tcp"])

def _setupVNC(url):
  libjpeg_ver = "2.0.3"
  virtualGL_ver = "2.6.2"
  turboVNC_ver = "2.2.3"

  libjpeg_url = "https://svwh.dl.sourceforge.net/project/libjpeg-turbo/{0}/libjpeg-turbo-official_{0}_amd64.deb".format(libjpeg_ver)
  virtualGL_url = "https://svwh.dl.sourceforge.net/project/virtualgl/{0}/virtualgl_{0}_amd64.deb".format(virtualGL_ver)
  turboVNC_url = "https://svwh.dl.sourceforge.net/project/turbovnc/{0}/turbovnc_{0}_amd64.deb".format(turboVNC_ver)

  _log('Installing VNC packages...')
  _download(libjpeg_url, "libjpeg-turbo.deb")
  _download(virtualGL_url, "virtualgl.deb")
  _download(turboVNC_url, "turbovnc.deb")

  cache = apt.Cache()
  apt.debfile.DebPackage("libjpeg-turbo.deb", cache).install()
  apt.debfile.DebPackage("virtualgl.deb", cache).install()
  apt.debfile.DebPackage("turbovnc.deb", cache).install()

  _log('Installing desktop environment...')
  _installPkgs(cache, "xfce4", "xfce4-terminal")
  cache.commit()

  _log('Installing extra packages...')
  _installPkgs(cache, "mesa-utils", "chromium-browser", "fonts-noto", "fonts-noto-cjk", "vim")
  cache.commit()


  vnc_sec_conf_p = pathlib.Path("/etc/turbovncserver-security.conf")
  vnc_sec_conf_p.write_text("""\
no-remote-connections
no-httpd
no-x11-tcp-connections
""")

  _log('Installing GPU driver...')
  gpu_name = _get_gpu_name()
  if gpu_name != None:
    _setup_nvidia_gl()

  _log('Starting VNC server...')
  vncrun_py = pathlib.Path("vncrun.py")
  vncrun_py.write_text("""\
import subprocess, secrets, pathlib, time

vnc_passwd = secrets.token_urlsafe()[:8]
vnc_viewonly_passwd = secrets.token_urlsafe()[:8]
print(vnc_passwd)
vncpasswd_input = "{0}\\n{1}".format(vnc_passwd, vnc_viewonly_passwd)
vnc_user_dir = pathlib.Path.home().joinpath(".vnc")
vnc_user_dir.mkdir(exist_ok=True)
vnc_user_passwd = vnc_user_dir.joinpath("passwd")
with vnc_user_passwd.open('wb') as f:
  subprocess.run(
    ["/opt/TurboVNC/bin/vncpasswd", "-f"],
    stdout=f,
    input=vncpasswd_input,
    universal_newlines=True)
vnc_user_passwd.chmod(0o600)
subprocess.run(
  ["/opt/TurboVNC/bin/vncserver"]
)

#Disable screensaver because no one would want it.
(pathlib.Path.home() / ".xscreensaver").write_text("mode: off\\n")

time.sleep(5)
subprocess.run(['gsettings', 'set', 'org.gnome.Terminal.Legacy.Profile:/org/gnome/terminal/legacy/profiles:/:b1dcc9dd-5262-4d8d-a863-c897e6d979b9/', 'use-system-font', 'false'], env={'DISPLAY': ':1'})
subprocess.run(['gsettings', 'set', 'org.gnome.Terminal.Legacy.Profile:/org/gnome/terminal/legacy/profiles:/:b1dcc9dd-5262-4d8d-a863-c897e6d979b9/', 'font', 'Noto Mono 12'], env={'DISPLAY': ':1'})
""")
  r = subprocess.run(
                    ["su", "-c", "python3 vncrun.py", "colab"],
                    check = True,
                    stdout = subprocess.PIPE,
                    universal_newlines = True)
  _log('Ready! Click here to connect: %s/vnc.html?autoconnect=1&resize=remote&password=%s' % (url, r.stdout))

def _setupProxy(url):
  proxy3_ver = "0.8.13"
  
  proxy3_url = "https://github.com/z3APA3A/3proxy/archive/{0}.tar.gz".format(proxy3_ver)
  
  proxy3_dir = "3proxy-{0}".format(proxy3_ver)
  proxy3_cfgfile = "/usr/local/etc/3proxy/3proxy.cfg"
  
  _log('Downloading and installing 3proxy...')
  _download(proxy3_url, "3proxy.tar.gz")
  tar = tarfile.open("3proxy.tar.gz", "r:gz")
  tar.extractall()
  tar.close()
  os.symlink(os.path.join(proxy3_dir, "Makefile.Linux"), os.path.join(proxy3_dir, "Makefile"))
  subprocess.run(["make", "-C", proxy3_dir])
  subprocess.run(["sudo", "make", "-C", proxy3_dir, "install"])
  with open(proxy3_cfgfile, "w+") as f:
    proxy_config = [
      "nserver 8.8.8.8",
      "daemon",
      "auth none",
      "external 0.0.0.0",
      "internal 0.0.0.0",
      "flush",
      "socks -aunp1080"
    ]
    f.write("\n".join(proxy_config))
    f.close()
  
  _log('Running the proxy server...')
  subprocess.run(["sudo", "3proxy", proxy3_cfgfile])
  
  _log('Ready!')
  index = url.find(":")
  print('Protocol: SOCKS5')
  if index != -1:
    print('Server: {0}'.format(url[:index]))
    print('Port: {0}'.format(url[index+1:]))
  else:
    print('Server: {0}'.format(url))

def setupProxy(ngrok_region=None, ngrok_token=None):
  _log('Starting...')
  url = setupSSHD(ngrok_region, ngrok_token, True)
  #_setupVNC(url)
  _setupProxy(url)
  while True:
    time.sleep(1)

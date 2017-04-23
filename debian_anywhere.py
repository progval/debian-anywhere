#!/usr/bin/env python
import os
import sys
import stat
import shutil
import tarfile
import tempfile
import functools
import subprocess

if sys.version_info >= (3,):
    from urllib.request import urlopen
else:
    from urllib2 import urlopen

if sys.version_info < (3, 3):
    FileExistsError = os.error

###########################
# Utilities

# from https://stackoverflow.com/a/377028/539465
def which(program):
    import os
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def is_installed(program):
    res = which(program)
    return bool(res)

def installer(f):
    command_name = f.__name__
    @functools.wraps(installer)
    def newf(self, *args, **kwargs):
        command = which(command_name)
        install_only = kwargs.pop('install_only', False)
        if not command:
            f(self, **kwargs)
            command = which(command_name)
            assert command
        if install_only:
            assert args == ()
        else:
            print('Calling %s with arguments: %r' % (command_name, args))
            subprocess.check_call((command,) + args)
    return newf

class UnnamedBufferedRandom:
    """Wrapper for BufferedRandom that does not have a 'name' attribute."""
    def __init__(self, obj):
        self.__obj = obj

    def __getattr__(self, attr_name):
        if attr_name == 'name':
            raise AttributeError()
        return getattr(self.__obj, attr_name)

    def __setattr__(self, attr_name, attr_value):
        if attr_name == '_UnnamedBufferedRandom__obj':
            super(UnnamedBufferedRandom, self).__setattr__(attr_name, attr_value)
        return setattr(self.__obj, attr_name, attr_value)

def download_tarball(tempdir, url):
    with tempfile.TemporaryFile() as fd:
        response = urlopen(url)
        try:
            fd.write(response.read()) # TODO: don't copy all at once
        finally:
            response.close()
        fd.seek(0)
        if hasattr(fd, 'name') and not isinstance(fd.name, str):
            # WTF, Python 3.2?! Why is fd.name an int?!
            fd = UnnamedBufferedRandom(fd)
        with tarfile.open(fileobj=fd) as tf:
            for name in tf.getnames():
                # See the warning:
                # https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.extractall
                assert not name.startswith('/')
            tf.extractall(tempdir)


########################
# Installers

class Commands:
    def __init__(self, target, utilsdir, tempdir):
        self._target = target
        self._utilsdir = utilsdir
        self._tempdir = tempdir

    def _configure(self, source_dir, prefix):
        # the 'configure' script writes its files to the CWD, so we have
        # to change it temporarily.
        # https://superuser.com/q/1077196/112844
        orig_cwd = os.getcwd()
        try:
            os.chdir(os.path.join(tempdir, source_dir))
            subprocess.check_call([
                './configure',
                '--prefix', prefix])
        finally:
            os.chdir(orig_cwd)

    def _make(self, source_dir):
        self.make(
                '-C', os.path.join(tempdir, source_dir),
                '-j', '4')

    def _make_install(self, source_dir):
        self.make('install',
                '-C', os.path.join(tempdir, source_dir))

    @installer
    def make(self):
        # Debian's make has no 'configure' script
        download_tarball(
                tempdir,
                'http://alpha.gnu.org/gnu/make/make-4.1.90.tar.bz2')
        self._configure(
                source_dir='make-4.1.90',
                prefix=self._tempdir)

        orig_cwd = os.getcwd()
        try:
            os.chdir(os.path.join(tempdir, 'make-4.1.90'))
            subprocess.check_call(['./build.sh'])
            subprocess.check_call(['./make', 'install'])
        finally:
            os.chdir(orig_cwd)
        assert is_installed('make'), \
                'Install of make did not add the executable in the PATH.'

    @installer
    def fakeroot(self):
        download_tarball(
                tempdir,
                'http://http.debian.net/debian/pool/main/f/fakeroot/fakeroot_1.20.2.orig.tar.bz2')
        self._configure(
                source_dir='fakeroot-1.20.2',
                prefix=self._utilsdir)
        self._make('fakeroot-1.20.2') # Does not build. Why?
        self._make_install('fakeroot-1.20.2')
        assert is_installed('fakeroot'), \
                'Install of fakeroot did not add the executable in the PATH.'

    def _patch_fakechroot(self):
        fc_base = os.path.join(tempdir, 'fakechroot-2.17.2')
        print('Patching fakechroot: %s' % fc_base)
        response = urlopen('https://raw.githubusercontent.com/sveniu/fakechroot/628237d9e421d6f882be32a061f8f786a0d47103/src/audit.c')
        with open(os.path.join(fc_base, 'src', 'audit.c'), 'ab') as fd:
            try:
                fd.write(response.read())
            finally:
                response.close()
        subprocess.check_call(['sed', '-i', 's/acct/acct\\n    audit/',
            os.path.join(fc_base, 'configure.ac')])
        subprocess.check_call(['sed', '-i', 's/acct.c/acct.c \\n    audit/',
            os.path.join(fc_base, 'src', 'Makefile.am')])

    @installer
    def fakechroot(self):
        download_tarball(
                tempdir,
                'http://http.debian.net/debian/pool/main/f/fakechroot/fakechroot_2.17.2.orig.tar.gz')
        self._patch_fakechroot()
        self._configure(
                source_dir='fakechroot-2.17.2',
                prefix=self._utilsdir)
        self._make('fakechroot-2.17.2')
        self._make_install('fakechroot-2.17.2')
        assert is_installed('fakechroot'), \
                'Install of fakechroot did not add the executable in the PATH.'

    @installer
    def debootstrap(self):
        download_tarball(
                tempdir,
                'http://http.debian.net/debian/pool/main/d/debootstrap/debootstrap_1.0.67.tar.gz')
        os.mkdir(os.path.join(self._tempdir, 'share'))
        os.mkdir(os.path.join(self._tempdir, 'share', 'debootstrap'))
        shutil.copy(
                os.path.join(self._tempdir, 'debootstrap-1.0.67', 'debootstrap'),
                os.path.join(self._tempdir, 'bin', 'debootstrap'))
        shutil.copy(
                os.path.join(self._tempdir, 'debootstrap-1.0.67', 'functions'),
                os.path.join(self._tempdir, 'share', 'debootstrap', 'functions'))
        shutil.copytree(
                os.path.join(self._tempdir, 'debootstrap-1.0.67', 'scripts'),
                os.path.join(self._tempdir, 'share', 'debootstrap', 'scripts'))

##################################
# chroot script

CHROOT_SH = """
PATH=%(target)s/utils/bin:$PATH
%(fakeroot)s %(fakechroot)s chroot %(target)s/root $@
"""

##################################
# Install commands


def main(target, tempdir):
    target = os.path.abspath(target)
    tempdir = os.path.abspath(tempdir)
    temp_bin_dir = os.path.join(tempdir, 'bin')
    try:
        os.makedirs(temp_bin_dir)
    except FileExistsError:
        pass
    utils_dir = os.path.join(target, 'utils')
    try:
        os.makedirs(utils_dir)
    except FileExistsError:
        pass
    utils_bin_dir = os.path.join(utils_dir, 'bin')
    os.environ['PATH'] = ':'.join([
        utils_bin_dir,
        temp_bin_dir,
        os.environ.get('PATH')])
    commands = Commands(target, utils_dir, tempdir)
    commands.debootstrap(install_only=True)
    commands.fakechroot(install_only=True)
    debootstrap_path = which('debootstrap')
    if debootstrap_path.startswith(tempdir):
        os.environ['DEBOOTSTRAP_DIR'] = os.path.join(tempdir, 'share', 'debootstrap')
    if os.environ.get('FAKECHROOT', '') == 'true':
        commands.fakeroot(debootstrap_path,
                '--variant=fakechroot',
                'stable',
                os.path.join(target, 'root'))
    else:
        commands.fakeroot(which('fakechroot'), which('debootstrap'),
                '--variant=fakechroot',
                'stable',
                os.path.join(target, 'root'))
    if debootstrap_path.startswith(tempdir):
        del os.environ['DEBOOTSTRAP_DIR']

    script_path = os.path.join(target, 'chroot.sh')
    with open(script_path, 'a') as fd:
        fd.write(CHROOT_SH % {
            'target': target,
            'fakeroot': which('fakeroot'),
            'fakechroot': which('fakechroot')})
    os.chmod(script_path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

if __name__ == '__main__':
    if len(sys.argv) == 2:
        (_, target) = sys.argv
        with tempfile.TemporaryDirectory() as tempdir:
            main(target, tempdir)
    elif len(sys.argv) == 3:
        (_, target, tempdir) = sys.argv
        main(target, tempdir)
    else:
        print('Syntax: %s <target> [<tempdir>]' % sys.argv[0])
        exit(1)

#!/usr/bin/env python
# Copyright European Organization for Nuclear Research (CERN)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# You may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0OA
#
# Authors:
# - Wen Guan, <wen.guan@cern.ch>, 2016


import os
import shutil
import subprocess
import sys
import tempfile
import imp
from distutils.spawn import find_executable

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PIP_REQUIRES = os.path.join(ROOT, 'tools', 'pip-requires')
PIP_REQUIRES_TEST = os.path.join(ROOT, 'tools', 'pip-requires-test')


def die(message, *args):
    print >> sys.stderr, message % args
    sys.exit(1)


def run_command(cmd, redirect_output=True, check_exit_code=True, shell=False):
    """
    Runs a command in an out-of-process shell, returning the
    output of that command.  Working directory is ROOT.
    """
    if shell:
        cmd = ['sh', '-c', cmd]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE if redirect_output else None)
    output = proc.communicate()[0]
    if check_exit_code and proc.returncode != 0:
        # print("ec = %d " % proc.returncode)
        die('Command "%s" failed.\n%s', ' '.join(cmd), output)
    return output


def has_module(mod):
    try:
        imp.find_module(mod)
        return True
    except ImportError:
        return False

HAS_PIP = has_module('pip')
HAS_WGET = bool(find_executable('wget'))


def configure_git():
    """
    Configure git to add git hooks
    """
    print "Configure git"
    run_command(['sh', "%s/tools/configure_git.sh" % ROOT])


def install_pip():
    """
    Install pip to tools/externals
    """
    print "Installing pip via wget"
    if not HAS_WGET:
        die("ERROR: wget not found, please install.")

    tempdir = tempfile.mkdtemp()
    run_command(['wget', '-O', os.path.join(tempdir, 'get-pip.py'), 'https://bootstrap.pypa.io/get-pip.py'])
    run_command([sys.executable, os.path.join(tempdir, "get-pip.py"),
                 '--root=' + os.path.join(ROOT, 'tools/externals'), "--ignore-installed"])
    shutil.rmtree(tempdir)


def install_dependencies():
    """
    Install external dependencies
    """
    lib_dir = os.path.join(ROOT, "tools", "externals", "usr", "lib")
    for pathname in os.listdir(lib_dir):
        if pathname.startswith('python'):
            lib_path = os.path.join(lib_dir, pathname)
            link_path = os.path.join(lib_dir, "python")
            if not os.path.exists(link_path):
                os.symlink(lib_path, link_path)
            elif not os.path.exists(os.readlink(link_path)):
                os.remove(link_path)
                os.symlink(lib_path, link_path)
    env_export = "export PYTHONPATH=$PYTHONPATH:./tools/externals/usr/lib/python/site-packages"
    # run_command("%s;%s/tools/externals/usr/bin/pip install -r %s -t %s/externals/" % (env_export, ROOT, PIP_REQUIRES,
    # ROOT), shell=True)
    run_command(['sh', '-c', "%s;./tools/externals/usr/bin/pip install -r %s --root=./tools/externals/" %
                (env_export, PIP_REQUIRES_TEST)])


def print_help():
    help = """
Pilot development environment setup is complete.

To enable pilot dev environment by running:

$ source tools/setup_dev.sh
"""
    print help


def main():
    configure_git()
    if not HAS_PIP:
        print "Installing pip via wget"
        install_pip()

    print "Installing dependencies via pip"
    install_dependencies()
    print_help()

if __name__ == "__main__":
    main()

#!/usr/bin/python
# coding=utf-8
from __future__ import print_function, unicode_literals

import sys
import errno
import fnmatch
import os
import re
import stat
import zipfile
import subprocess
from os.path import join
from shutil import copytree, copy2, rmtree as _rmtree
from subprocess import check_output, STDOUT, CalledProcessError


PY2 = sys.version_info[0] < 3

try:
    input = raw_input
except NameError:
    pass

if PY2:
    import io
    # add support for encoding. Slow on Python2, but that is not a problem given what we do with it.
    open = io.open


# ------------- #
# generic tools #
# ------------- #

def size2str(value):
    unit = "bytes"
    if value > 1024.0:
        value /= 1024.0
        unit = "Kb"
        if value > 1024.0:
            value /= 1024.0
            unit = "Mb"
        return "{:.2f} {}".format(value, unit)
    else:
        return "{:d} {}".format(value, unit)


def generate(fname, **kwargs):
    with open('{}.tmpl'.format(fname)) as in_f, open(fname, 'w') as out_f:
        out_f.write(in_f.read().format(**kwargs))


def _remove_readonly(function, path, excinfo):
    if function in (os.rmdir, os.remove) and excinfo[1].errno == errno.EACCES:
        # add write permission to owner
        os.chmod(path, stat.S_IWUSR)
        # retry removing
        function(path)
    else:
        raise Exception("Cannot remove {}".format(path))


def rmtree(path):
    _rmtree(path, onerror=_remove_readonly)


def call(*args, **kwargs):
    try:
        res = check_output(*args, stderr=STDOUT, **kwargs)
        if not PY2 and 'universal_newlines' not in kwargs:
            res = res.decode('utf8')
        return res
    except CalledProcessError as e:
        print(e.output)
        raise e


def echocall(*args, **kwargs):
    print(' '.join(args))
    return call(*args, **kwargs)


def branchname(statusline):
    """
    computes the branch name from a "git status -b -s" line
    ## master...origin/master
    """
    statusline = statusline.replace('#', '').strip()
    pos = statusline.find('...')
    return statusline[:pos] if pos != -1 else statusline


def yes(msg, default='y'):
    choices = ' ({}/{}) '.format(*tuple(c.capitalize() if c == default else c
                                  for c in ('y', 'n')))
    answer = None
    while answer not in ('', 'y', 'n'):
        if answer is not None:
            print("answer should be 'y', 'n', or <return>")
        answer = input(msg + choices).lower()
    return (default if answer == '' else answer) == 'y'


def no(msg, default='n'):
    return not yes(msg, default)


def do(description, func, *args, **kwargs):
    print(description + '...', end=' ')
    func(*args, **kwargs)
    print("done.")


def allfiles(pattern, path='.'):
    """
    like glob.glob(pattern) but also include files in subdirectories
    """
    return (os.path.join(dirpath, f)
            for dirpath, dirnames, files in os.walk(path)
            for f in fnmatch.filter(files, pattern))


def zip_pack(archivefname, filepattern):
    with zipfile.ZipFile(archivefname, 'w', zipfile.ZIP_DEFLATED) as f:
        for fname in allfiles(filepattern):
            f.write(fname)


def zip_unpack(archivefname, dest=None):
    with zipfile.ZipFile(archivefname) as f:
        f.extractall(dest)


def short(rel_name):
    return rel_name[:-2] if rel_name.endswith('.0') else rel_name


def long_release_name(release_name):
    """
    transforms a short release name such as 0.8 to a long one such as 0.8.0
    >>> long_release_name('0.8')
    '0.8.0'
    >>> long_release_name('0.8.0')
    '0.8.0'
    >>> long_release_name('0.8rc1')
    '0.8.0rc1'
    >>> long_release_name('0.8.0rc1')
    '0.8.0rc1'
    """
    dotcount = release_name.count('.')
    if dotcount >= 2:
        return release_name
    assert dotcount == 1, "{} contains {} dots".format(release_name, dotcount)
    pos = pretag_pos(release_name)
    if pos is not None:
        return release_name[:pos] + '.0' + release_name[pos:]
    return release_name + '.0'


def pretag_pos(release_name):
    """
    gives the position of any pre-release tag
    >>> pretag_pos('0.8')
    >>> pretag_pos('0.8alpha25')
    3
    >>> pretag_pos('0.8.1rc1')
    5
    """
    # 'a' needs to be searched for after 'beta'
    for tag in ('rc', 'c', 'beta', 'b', 'alpha', 'a'):
        match = re.search(tag + '\d+', release_name)
        if match is not None:
            return match.start()
    return None


def strip_pretags(release_name):
    """
    removes pre-release tags from a version string
    >>> strip_pretags('0.8')
    '0.8'
    >>> strip_pretags('0.8alpha25')
    '0.8'
    >>> strip_pretags('0.8.1rc1')
    '0.8.1'
    """
    pos = pretag_pos(release_name)
    return release_name[:pos] if pos is not None else release_name


def isprerelease(release_name):
    """
    tests whether the release name contains any pre-release tag
    >>> isprerelease('0.8')
    False
    >>> isprerelease('0.8alpha25')
    True
    >>> isprerelease('0.8.1rc1')
    True
    """
    return pretag_pos(release_name) is not None


# -------------------- #
# end of generic tools #
# -------------------- #

# ---------------- #
# helper functions #
# ---------------- #


def relname2fname(release_name):
    short_version = short(strip_pretags(release_name))
    return r"version_{}.rst.inc".format(short_version.replace('.', '_'))


def release_changes(config):
    if 'src_documentation' in config:
        directory = join(config['src_documentation'], "changes")
        fname = relname2fname(config['release_name'])
        with open(os.path.join(config['build_dir'], directory, fname), encoding='utf-8-sig') as f:
            return f.read()


def replace_lines(fpath, changes, end="\n"):
    """
    Parameters
    ----------
    changes : list of pairs
        List of pairs (substring_to_find, new_line).
    """
    with open(fpath) as f:
        lines = f.readlines()
        for i, line in enumerate(lines[:]):
            for substring_to_find, new_line in changes:
                if substring_to_find in line and not line.strip().startswith('#'):
                    lines[i] = new_line + end
    with open(fpath, 'w') as f:
        f.writelines(lines)

def git_remote_last_rev(url, branch=None):
    """
    :param url: url of the remote repository
    :param branch: an optional branch (defaults to 'refs/heads/master')
    :return: name/hash of the last revision
    """
    if branch is None:
        branch = 'refs/heads/master'
    output = call(['git', 'ls-remote', url, branch])
    for line in output.splitlines():
        if line.endswith(branch):
            return line.split()[0]
    raise Exception("Could not determine revision number")


# ----------------------- #
# end of helper functions #
# ----------------------- #
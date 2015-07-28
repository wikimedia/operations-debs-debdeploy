# Partially based on checkrestart from debian-goodies:
# Copyright (C) 2001 Matt Zimmerman <mdz@debian.org>
# Copyright (C) 2007,2010-2015 Javier Fernandez-Sanguino <jfs@debian.org>
# - included patch from Justin Pryzby <justinpryzby_AT_users.sourceforge.net>
#   to work with the latest Lsof - modify to reduce false positives by not
#   complaining about deleted inodes/files under /tmp/, /var/log/,
#   /var/run or named   /SYSV. 
# - introduced a verbose option
#
# Additional changes:
# Copyright (C) 2015 Moritz Muehlenhoff <moritz@wikimedia.org>
# Copyright (C) 2015 Wikimedia Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, 
# MA 02110-1301 USA
#
# On Debian systems, a copy of the GNU General Public License may be
# found in /usr/share/common-licenses/GPL.

import os, errno, sys, re, pwd, sys, subprocess, getopt
from stat import *

# Tells if a file has to be considered a deleted file
# Returns:
#  - 0 (NO) for known locations of files which might be deleted
#  - 1 (YES) for valid deleted files we are interested in
def isdeletedFile (f, blacklist = None):

    if blacklist:
        for p in blacklist:
            if p.search(f):
                return 0
    if f.startswith('/var/log/') or f.startswith('/var/local/log/'):
        return 0
    if f.startswith('/var/run/') or f.startswith('/var/local/run/'):
        return 0
    if f.startswith('/tmp/'):
        return 0
    if f.startswith('/dev/shm/'):
        return 0
    if f.startswith('/run/'):
        return 0
    if f.startswith('/drm'):
        return 0
    if f.startswith('/var/tmp/') or f.startswith('/var/local/tmp/'):
        return 0
    if f.startswith('/dev/zero'):
        return 0
    if f.startswith('/dev/pts/'):
        return 0
    if f.startswith('/usr/lib/locale/'):
        return 0
    # Skip files from the user's home directories
    # many processes hold temporary files there 
    if f.startswith('/home/'):
        return 0
    # Skip automatically generated files
    if f.endswith('icon-theme.cache'):
        return 0
    if f.startswith('/var/cache/fontconfig/'):
        return 0
    if f.startswith('/var/lib/nagios3/spool/'):
        return 0
    if f.startswith('/var/lib/nagios3/spool/checkresults/'):
	return 0
    if f.startswith('/var/lib/postgresql/'):
        return 0
    # Skip Aio files found in MySQL servers
    if f.startswith('/[aio]'):
        return 0

    # TODO: it should only care about library files (i.e. /lib, /usr/lib and the like)
    # build that check with a regexp to exclude others
    if f.endswith(' (deleted)'):
        return 1
    if re.compile("\(path inode=[0-9]+\)$").search(f):
        return 1
    # Default: it is a deleted file we are interested in
    return 1

class Package:
    def __init__(self, name):
        self.name = name
        # use a set, we don't need duplicates
        self.initscripts = set()
        self.systemdservice = set()
        self.processes = []

class Process:
    def __init__(self, pid):
        self.pid = pid
        self.files = []
        self.descriptors = []
        self.links = []
        self.program = ''

        try:
            self.program = os.readlink('/proc/%d/exe' % self.pid)
            # if the executable command is an interpreter such as perl/python/ruby/tclsh,
            # we want to find the real program
            m = re.match("^/usr/bin/(perl|python|ruby|tclsh)", self.program)
            if m:
                with open('/proc/%d/cmdline' % self.pid, 'r') as cmdline:
                    # only match program in /usr (ex.: /usr/sbin/smokeping)
                    # ignore child, etc.
                    #m = re.search(r'^(([/]\w*){1,5})\s.*$', cmdline.read())
                    # Split by null-bytes, see proc(5)
                    data = cmdline.read().split('\x00')
                    # Last character should be null-byte, too, see proc(5)
                    if not data[-1]: data.pop()
                    # Spamd sets $0 wrongly, see
                    # https://bugzilla.redhat.com/show_bug.cgi?id=755644
                    # i.e. the blank after spamd is relevant in case
                    # this will be fixed in the future.
                    m = re.match("^/usr/sbin/spamd |^spamd ", data[0])
                    if m:
                        self.program = "/usr/sbin/spamd"
                    else:
                        # Strip first value, the interpreter
                        data.pop(0)
                        # Check if something's left after the interpreter, see #715000
                        if data:
                            # Strip all options following the interpreter, e.g. python's -O
                            m = re.match("^-", data[0])
                            while (m):
                                data.pop(0)
                                if not data: break
                                m = re.match("^-", data[0])
                            if data and data[0]:
                                data = self.which(data[0])
                                m = re.search(r'^(/usr/\S+)$', data)
                                if m:
                                    # store the real full path of script as the program
                                    self.program = m.group(1)
        except OSError, e:
            if e.errno != errno.ENOENT:
                if self.pid == 1:
                    sys.stderr.write("Found unreadable pid 1. Assuming we're under vserver and continuing.\n")
                else:
                    sys.stderr.write('ERROR: Failed to read %d' % self.pid)
                    raise
        self.program = self.cleanFile(self.program)

    def which(self, program):
        if os.path.isabs(program):
            return program
        path = os.environ.get("PATH", os.defpath).split(os.pathsep)
        seen = set()
        for dir in path:
            dir = os.path.normcase(os.path.abspath(dir))
            if not dir in seen:
                seen.add(dir)
                name = os.path.join(dir, program)
                if os.path.exists(name) and os.access(name, os.F_OK|os.X_OK) and not os.path.isdir(name):
                    return name
        return program

    def cleanFile(self, f):
        # /proc/pid/exe has all kinds of junk in it sometimes
        null = f.find('\0')
        if null != -1:
            f = f[:null]
        # Support symlinked /usr
        if f.startswith('/usr'):
            statinfo = os.lstat('/usr')[ST_MODE]
            # If /usr is a symlink then find where it points to
            if S_ISLNK(statinfo): 
                newusr = os.readlink('/usr')
                if not newusr.startswith('/'):
                    # If the symlink is relative, make it absolute
                    newusr = os.path.join(os.path.dirname('/usr'), newusr)
                f = re.sub('^/usr',newusr, f)
                # print "Changing usr to " + newusr + " result:" +f; # Debugging
        return re.sub('( \(deleted\)|.dpkg-new).*$','',f)

    # Check if a process needs to be restarted, previously we would
    # just check if it used libraries named '.dpkg-new' since that's
    # what dpkg would do. Now we need to be more contrieved.
    # Returns:
    #  - 0 if there is no need to restart the process
    #  - 1 if the process needs to be restarted
    def needsRestart(self, blacklist = None):
        for f in self.files:
            if isdeletedFile(f, blacklist):
	    	return 1
	for f in self.links:
	    if f == 0:
	    	return 1
        return 0

class Checkrestart:
    def __init__(self):
        if os.getuid() != 0:
            sys.stderr.write('ERROR: This program must be run as root in order to obtain information\n')
            sys.stderr.write('about all open file descriptors in the system.\n')
            sys.exit(1)

        process = None
        toRestart = {}

        lc_all_c_env = os.environ
        lc_all_c_env['LC_ALL'] = 'C'
        blacklistFiles = []
        blacklist = []
        ignorelist = [ 'screen', 'systemd' ]

        for f in blacklistFiles:
            for line in file(f, "r"):
                if line.startswith("#"):
                    continue
                blacklist.append(re.compile(line.strip()))

        toRestart = self.lsoffilescheck(blacklist = blacklist)

        self.programs = {}
        for process in toRestart:
            self.programs.setdefault(process.program, [])
            self.programs[process.program].append(process)

        self.packages = {}
        diverted = None

        dpkgQuery = ["dpkg-query", "--search"] + self.programs.keys()
        dpkgProc = subprocess.Popen(dpkgQuery, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env = lc_all_c_env)

        while True:
            line = dpkgProc.stdout.readline()
            if not line:
                break
            if line.startswith('local diversion'):
                continue
            if not ':' in line:
                continue

            m = re.match('^diversion by (\S+) (from|to): (.*)$', line)
            if m:
                if m.group(2) == 'from':
                    diverted = m.group(3)
                    continue
                if not diverted:
                    raise Exception('Weird error while handling diversion')
                packagename, program = m.group(1), diverted
            else:
                packagename, program = line[:-1].split(': ')
                if program == diverted:
                    # dpkg prints a summary line after the diversion, name both
                    # packages of the diversion, so ignore this line
                    # mutt-patched, mutt: /usr/bin/mutt
                    continue
            self.packages.setdefault(packagename,Package(packagename))
            try:
                 self.packages[packagename].processes.extend(self.programs[program])
            except KeyError:
                  sys.stderr.write ('checkrestart (program not found): %s: %s\n' % (packagename, program))
            sys.stdout.flush()

        dpkgProc.stdout.close()

        # Remove the ignored packages from the list of packages
        if ignorelist:
            for i in ignorelist:
                if i in self.packages:
                    try:
                        del self.packages[i]
                    except KeyError:
                        continue

    def get_packages_to_restart(self):
        return set(self.packages.keys())

    def get_programs_to_restart(self):
        return set(self.programs.keys())
    
    def lsoffilescheck(self, blacklist = None):
        processes = {}

        for line in os.popen('lsof +XL -F nf').readlines():
            field, data = line[0], line[1:-1]

            if field == 'p':
                process = processes.setdefault(data,Process(int(data)))
            elif field == 'k':
                process.links.append(data)
            elif field == 'n':
                # Remove the previous entry to check if this is something we should use
                if data.find('SYSV') >= 0:
                    # If we find SYSV we discard the previous descriptor
                    last = process.descriptors.pop()
                elif data.startswith('/') or data.startswith('(deleted)/') or data.startswith(' (deleted)/'):
                    last = process.descriptors.pop()

                    # If the data starts with (deleted) put it in the end of the
                    # file name, this is used to workaround different behaviour in
                    # OpenVZ systems, see
                    # https://bugzilla.openvz.org/show_bug.cgi?id=2932
                    if data.startswith('(deleted)'):
                        data = data[9:] + ' (deleted)'
                    elif data.startswith(' (deleted)'):
                        data = data[10:] + ' (deleted)'

                    # Add it to the list of deleted files if the previous descriptor
                    # was DEL or lsof marks it as deleted
                    if re.compile("DEL").search(last) or re.compile("\(deleted\)").search(data) or re.compile("\(path inode=[0-9]+\)$").search(data):
                        process.files.append(data)
                else:
                    # We discard the previous descriptors and drop it
                    last = process.descriptors.pop()
            elif field == 'f':
                # Save the descriptor for later comparison
                process.descriptors.append(data)

        toRestart = filter(lambda process: process.needsRestart(blacklist),
                       processes.values())
        return toRestart














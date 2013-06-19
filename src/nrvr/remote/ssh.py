#!/usr/bin/python

"""nrvr.remote.ssh - Remote commands over ssh

The main class provided by this module is SshCommand.

On the downside, for now it
* reports back indistinguishably the same way stdout and stderr,
* doesn't report back the command's returncode.

Works only if module pty is available (e.g. in Python 2.6 on Linux, but not on Windows).

As implemented works in Linux.
As implemented requires ssh command.
Nevertheless essential.  To be improved as needed.

Idea and first implementation - Leo Baschy <srguiwiz12 AT nrvr DOT com>

Public repository - https://github.com/srguiwiz/nrvr-commander

Copyright (c) Nirvana Research 2006-2013.
Modified BSD License"""

import os.path
import re
import sys
import time

from nrvr.util.classproperty import classproperty
from nrvr.util.ipaddress import IPAddress

_gotPty = False
try:
    import pty
    _gotPty = True
except ImportError:
    pass

class SshCommandException(Exception):
    def __init__(self, message):
        self._message = message
    def __str__(self):
        return unicode(self._message)
    @property
    def message(self):
        return self._message

class SshCommand(object):
    """Send a command over ssh."""

    @classmethod
    def commandsUsedInImplementation(cls):
        """Return a list to be passed to SystemRequirements.commandsRequired().
        
        This class captures returncode, and output.
        
        This class can be passed to SystemRequirements.commandsRequiredByImplementations()."""
        return ["ssh"]

    def __init__(self, ipaddress, argv, user, pwd,
                 exceptionIfNotZero=True,
                 pwdPrompt=r"password:", acceptPrompt=r"(yes/no)?"):
        """Create new SshCommand instance.
        
        Will wait until completed.
        
        ipaddress
            IP address or domain name.
        
        argv
            list of command and arguments passed to ssh.
        
        user
            a string.
        
        pwd
            a string or None.
        
        pwdPrompt
            a string or a regular expression object.
            
            If not a regular expression object already then does re.compile(re.escape(pwdPrompt)).
            
            Don't bother unless default doesn't work.
        
        acceptPrompt
            a string or a regular expression object.
            
            If not a regular expression object already then does re.compile(re.escape(acceptPrompt)).
            
            Don't bother unless default doesn't work.
        
        Output may contain extraneous leading or trailing newlines and whitespace.
        
        Example use::
        
            example = SshCommand("10.123.45.67", ["ls", "-al"], "joe", "redwood")
            print "returncode=" + str(example.returncode)
            print "output=" + example.output"""
        if not _gotPty:
            # cannot use ssh if no pty
            raise Exception("must have module pty available to use ssh command"
                            ", which is known to be available in Python 2.6 on Linux, but not on Windows")
        #
        self._ipaddress = IPAddress.asString(ipaddress)
        self._argv = argv
        self._user = user
        self._pwd = pwd
        self._exceptionIfNotZero = exceptionIfNotZero
        if self._pwd:
            if type(pwdPrompt) != SshCommand._regexType:
                self._pwdPromptRegex = re.compile(re.escape(pwdPrompt))
            else:
                # a regular expression object already
                self._pwdPromptRegex = pwdPrompt
            if type(acceptPrompt) != SshCommand._regexType:
                self._acceptPromptRegex = re.compile(re.escape(acceptPrompt))
            else:
                # a regular expression object already
                self._acceptPromptRegex = acceptPrompt
        self._output = ""
        self._returncode = None
        #
        # fork and connect child to a pseudo-terminal
        self._pid, self._fd = pty.fork()
        if self._pid == 0:
            # in child process
            os.execvp("ssh", ["ssh", "-l", self._user, self._ipaddress] + self._argv)
        else:
            # in parent process
            if self._pwd:
                # if given a password then apply
                promptedForPassword = False
                outputTillPrompt = ""
                # look for password prompt
                while not promptedForPassword:
                    try:
                        newOutput = os.read(self._fd, 1024)
                        if not len(newOutput):
                            # end has been reached
                            # was raise Exception("unexpected end of output from ssh")
                            raise Exception("failing to connect via ssh\n" + 
                                            outputTillPrompt)
                        # ssh has been observed returning "\r\n" for newline, but we want "\n"
                        newOutput = SshCommand._crLfRegex.sub("\n", newOutput)
                        outputTillPrompt += newOutput
                        if self._acceptPromptRegex.search(outputTillPrompt):
                            # e.g. "Are you sure you want to continue connecting (yes/no)? "
                            raise Exception("cannot proceed unless having accepted host key\n" + 
                                            outputTillPrompt + 
                                            "\nE.g. invoke SshCommand.acceptKnownHostKey({0}).".format(self._ipaddress))
                        if self._pwdPromptRegex.search(outputTillPrompt):
                            # e.g. "10.123.45.67's password: "
                            promptedForPassword = True
                    except EnvironmentError:
                        # e.g. "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @" and closing
                        raise Exception("failing to connect via ssh\n" + 
                                        outputTillPrompt)
                os.write(self._fd, self._pwd + "\n")
            # look for output
            endOfOutput = False
            outputSincePrompt = ""
            try:
                while not endOfOutput:
                    try:
                        newOutput = os.read(self._fd, 1024)
                        if len(newOutput):
                            outputSincePrompt += newOutput
                        else:
                            # end has been reached
                            endOfOutput = True
                    except EnvironmentError as e:
                        # some ideas maybe at http://bugs.python.org/issue5380
                        if e.errno == 5: # errno.EIO:
                            # seen when pty closes OSError: [Errno 5] Input/output error
                            endOfOutput = True
                        else:
                            # we accept what we got so far, for now
                            endOfOutput = True
            finally:
                # remove any leading space (maybe there after "password:" prompt) and
                # remove first newline (is there after entering password and "\n")
                self._output = re.sub(r"^\s*?\n(.*)$", r"\1", outputSincePrompt)
                #
                # get returncode
                try:
                    ignorePidAgain, waitEncodedStatusIndication = os.waitpid(self._pid, 0)
                    if os.WIFEXITED(waitEncodedStatusIndication):
                        # normal exit(status) call
                        self._returncode = os.WEXITSTATUS(waitEncodedStatusIndication)
                        # raise an exception if asked to and there is a reason
                        exceptionMessage = ""
                        if self._exceptionIfNotZero and self._returncode:
                            exceptionMessage += "returncode: " + str(self._returncode)
                        if exceptionMessage:
                            commandDescription = "ipaddress: " + self._ipaddress
                            commandDescription += "\ncommand:\n\t" + self._argv[0]
                            if len(self._argv) > 1:
                                commandDescription += "\narguments:\n\t" + "\n\t".join(self._argv[1:])
                            else:
                                commandDescription += "\nno arguments"
                            commandDescription += "\nuser: " + self._user
                            exceptionMessage = commandDescription + "\n" + exceptionMessage
                            exceptionMessage += "\noutput:\n" + self._output
                            raise SshCommandException(exceptionMessage)
                    else:
                        # e.g. os.WIFSIGNALED or os.WIFSTOPPED
                        self._returncode = -1
                        raise SshCommandException("ssh did not exit normally")
                except OSError:
                    # supposedly can occur
                    self._returncode = -1
                    raise SshCommandException("ssh did not exit normally")

    @property
    def output(self):
        """Collected output string of command.
        
        May contain extraneous leading or trailing newlines and whitespace."""
        return self._output

    @property
    def returncode(self):
        """Returncode of command or 255 if an ssh error occurred.
        
        Could be None."""
        return self._returncode

    # auxiliary
    _crLfRegex = re.compile(r"\r\n")
    _regexType = type(_crLfRegex)

    @classproperty
    def _knownHostFilePath(cls):
        """Path of the known_host file."""
        return os.path.expanduser("~/.ssh/known_hosts")

    @classmethod
    def removeKnownHostKey(cls, ipaddress):
        """Remove line from ~/.ssh/known_hosts file."""
        knownHostsFile = cls._knownHostFilePath
        ipaddress = IPAddress.asString(ipaddress)
        if not os.path.exists(knownHostsFile):
            # maybe file hasn't been created yet, nothing to do
            return
        with open (knownHostsFile, "r") as inputFile:
            knownHostLines = inputFile.readlines()
        ipaddressRegex = re.compile(r"^[ \t]*" + re.escape(ipaddress) + r"\s")
        anyMatch = False
        newKnownHostLines = []
        for knownHostLine in knownHostLines:
            if ipaddressRegex.search(knownHostLine):
                # a match, don't copy it over
                anyMatch = True
            else:
                # all others copy over
                newKnownHostLines.append(knownHostLine)
        if anyMatch:
            with open (knownHostsFile, "w") as outputFile:
                outputFile.writelines(newKnownHostLines)

    @classmethod
    def acceptKnownHostKey(cls, ipaddress, acceptPrompt=r"(yes/no)?", acceptAnswer="yes\n"):
        """Accept host's key.
        
        Will wait until completed.
        
        ipaddress
            IP address or domain name.
        
        acceptPrompt
            a string or a regular expression object.
            
            If not a regular expression object already then does re.compile(re.escape(acceptPrompt)).
            
            Don't bother unless default doesn't work.
        
        acceptAnswer
            a string, explicitly containing any "\n" if needed.
            
            Don't bother unless default doesn't work."""
        if not _gotPty:
            # cannot use ssh if no pty
            raise Exception("must have module pty available to use ssh command"
                            ", which is known to be available in Python 2.6 on Linux, but not on Windows")
        #
        # remove any pre-existing key, if any
        cls.removeKnownHostKey(ipaddress)
        #
        ipaddress = IPAddress.asString(ipaddress)
        if type(acceptPrompt) != SshCommand._regexType:
            acceptPromptRegex = re.compile(re.escape(acceptPrompt))
        else:
            # a regular expression object already
            acceptPromptRegex = acceptPrompt
        #
        # fork and connect child to a pseudo-terminal
        pid, fd = pty.fork()
        if pid == 0:
            # in child process,
            # user "dummy" doesn't give away information about this script's user,
            # command "exit" if it would ever execute should be harmless
            os.execvp("ssh", ["ssh", "-l", "dummy", ipaddress, "exit"])
        else:
            # in parent process
            promptedForAccept = False
            outputTillPrompt = ""
            # look for accept prompt
            while not promptedForAccept:
                try:
                    newOutput = os.read(fd, 1024)
                    if not len(newOutput):
                        # end has been reached
                        # was raise Exception("unexpected end of output from ssh")
                        raise Exception("failing to connect via ssh\n" + 
                                        outputTillPrompt)
                    # ssh has been observed returning "\r\n" for newline, but we want "\n"
                    newOutput = SshCommand._crLfRegex.sub("\n", newOutput)
                    outputTillPrompt += newOutput
                    if acceptPromptRegex.search(outputTillPrompt):
                        # e.g. "Are you sure you want to continue connecting (yes/no)? "
                        promptedForAccept = True
                except EnvironmentError:
                    # e.g. "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @" and closing
                    raise Exception("failing to connect via ssh\n" + 
                                    outputTillPrompt)
            # do a special dance here to avoid being quicker to next invocation than
            # this invocation takes to get around to writing known_hosts file,
            # which would cause only one of the ssh invocations to write known_hosts file,
            # which has been observed as a problem in bulk processing
            startTime = time.time()
            knownHostsFile = cls._knownHostFilePath
            if os.path.exists(knownHostsFile):
                # normal case
                originalModificationTime = os.path.getctime(knownHostsFile)
            else:
                # maybe file hasn't been created yet
                originalModificationTime = startTime
            if originalModificationTime > startTime:
                # fix impossible future time
                os.utime(knownHostsFile, (startTime, startTime))
            while originalModificationTime == startTime:
                # wait to make sure modification will be after originalModificationTime
                time.sleep(0.1)
                startTime = time.time()
            # actually accept, one line in the middle of the special dance
            os.write(fd, acceptAnswer)
            # continue special dance
            looksDone = False
            while not looksDone:
                if os.path.exists(knownHostsFile):
                    # normal case
                    currentModificationTime = os.path.getctime(knownHostsFile)
                else:
                    # maybe file hasn't been created yet
                    currentModificationTime = originalModificationTime
                if currentModificationTime != originalModificationTime:
                    # has been modified
                    looksDone = True
                    break
                currentTime = time.time()
                if currentTime - startTime > 3.0:
                    # don't want to block forever, done or not
                    looksDone = True
                    break
                # sleep
                time.sleep(0.1)
            # NOT os.close(fd) because has been observed to prevent ssh writing known_hosts file,
            # instead enter a dummy password to accelerate closing of ssh port
            os.write(fd, "bye\n")

    @classmethod
    def isAvailable(cls, ipaddress, user, pwd,
                    probingCommand="hostname",
                    pwdPrompt=r"password:", acceptPrompt=r"(yes/no)?"):
        """Return whether probingCommand succeeds.
        
        Will wait until completed."""
        try:
            sshCommand = SshCommand(ipaddress=ipaddress,
                                    argv=[probingCommand],
                                    user=user,
                                    pwd=pwd,
                                    pwdPrompt=pwdPrompt,
                                    acceptPrompt=acceptPrompt)
            return True
        except Exception as e:
            return False

    @classmethod
    def sleepUntilIsAvailable(cls, ipaddress, user, pwd,
                              checkIntervalSeconds=5.0, ticker=False,
                              probingCommand="hostname",
                              pwdPrompt=r"password:", acceptPrompt=r"(yes/no)?"):
        """If available return, else loop sleeping for checkIntervalSeconds."""
        printed = False
        ticked = False
        # check the essential condition, initially and then repeatedly
        while not SshCommand.isAvailable(ipaddress=ipaddress,
                                         user=user,
                                         pwd=pwd,
                                         probingCommand=probingCommand,
                                         pwdPrompt=pwdPrompt,
                                         acceptPrompt=acceptPrompt):
            if not printed:
                # first time only printing
                print "waiting for ssh to be available to connect to " + ipaddress
                printed = True
            if ticker:
                if not ticked:
                    # first time only printing
                    sys.stdout.write("[")
                sys.stdout.write(".")
                sys.stdout.flush()
                ticked = True
            time.sleep(checkIntervalSeconds)
        if ticked:
            # final printing
            sys.stdout.write("]\n")

    @classmethod
    def hasAcceptedKnownHostKey(cls, ipaddress, acceptPrompt=r"(yes/no)?", acceptAnswer="yes\n"):
        """Return whether acceptKnownHostKey() succeeds.
        
        Will wait until completed."""
        try:
            SshCommand.acceptKnownHostKey(ipaddress=ipaddress,
                                          acceptPrompt=acceptPrompt,
                                          acceptAnswer=acceptAnswer)
            return True
        except Exception as e:
            return False

    @classmethod
    def sleepUntilHasAcceptedKnownHostKey(cls, ipaddress,
                                          checkIntervalSeconds=5.0, ticker=False,
                                          acceptPrompt=r"(yes/no)?", acceptAnswer="yes\n"):
        """If available return, else loop sleeping for checkIntervalSeconds."""
        printed = False
        ticked = False
        # check the essential condition, initially and then repeatedly
        while not SshCommand.hasAcceptedKnownHostKey(ipaddress=ipaddress,
                                                     acceptPrompt=acceptPrompt,
                                                     acceptAnswer=acceptAnswer):
            if not printed:
                # first time only printing
                print "waiting for ssh to be available to get host key from " + ipaddress
                printed = True
            if ticker:
                if not ticked:
                    # first time only printing
                    sys.stdout.write("[")
                sys.stdout.write(".")
                sys.stdout.flush()
                ticked = True
            time.sleep(checkIntervalSeconds)
        if ticked:
            # final printing
            sys.stdout.write("]\n")

if __name__ == "__main__":
    from nrvr.util.requirements import SystemRequirements
    SystemRequirements.commandsRequiredByImplementations([SshCommand], verbose=True)
    #
    SshCommand.removeKnownHostKey("localhost")
    SshCommand.acceptKnownHostKey("localhost")
    # fictional 10.123.45.67
#    _sshExample1 = SshCommand("10.123.45.67", ["hostname"], "root", "redwood")
#    print "returncode=" + str(_sshExample1.returncode)
#    print "output=" + _sshExample1.output
#    _sshExample2 = SshCommand("10.123.45.67", ["ls"], "root", "redwood")
#    print "returncode=" + str(_sshExample2.returncode)
#    print "output=" + _sshExample2.output
#    _sshExample3 = SshCommand("10.123.45.67", ["ls", "-al"], "root", "redwood")
#    print "returncode=" + str(_sshExample3.returncode)
#    print "output=" + _sshExample3.output
#    _sshExample4 = SshCommand("10.123.45.67", ["ls", "doesntexist"], "root", "redwood", exceptionIfNotZero=False)
#    print "returncode=" + str(_sshExample4.returncode)
#    print "output=" + _sshExample4.output
#    _sshExample5 = SshCommand("10.123.45.67", ["ls", "doesntexist"], "root", "redwood")
#    print "returncode=" + str(_sshExample5.returncode)
#    print "output=" + _sshExample5.output


class ScpCommandException(SshCommandException):
    def __init__(self, message):
        SshCommandException.__init__(self, message)

class ScpCommand(object):
    """Copy a file or files via scp."""

    @classmethod
    def commandsUsedInImplementation(cls):
        """Return a list to be passed to SystemRequirements.commandsRequired().
        
        This class captures returncode, and output.
        
        This class can be passed to SystemRequirements.commandsRequiredByImplementations()."""
        return ["scp"]

    def __init__(self,
                 fromPath, toPath, pwd,
                 fromUser=None, fromIpaddress=None,
                 toUser=None, toIpaddress=None,
                 pwdPrompt=r"password:", acceptPrompt=r"(yes/no)?"):
        """Create new ScpCommand instance.
        
        Will wait until completed.
        
        Either fromPath or toPath is expected to be local, i.e. without user and without IP address."""
        if not _gotPty:
            # cannot use scp if no pty
            raise Exception("must have module pty available to use scp command"
                            ", which is known to be available in Python 2.6 on Linux, but not on Windows")
        #
        fromIpaddress = IPAddress.asString(fromIpaddress) if fromIpaddress is not None else None
        toIpaddress = IPAddress.asString(toIpaddress) if toIpaddress is not None else None
        #
        if fromUser is not None and fromIpaddress is None:
            raise Exception("cannot handle if given user but not IP address")
        if toUser is not None and toIpaddress is None:
            raise Exception("cannot handle if given user but not IP address")
        if fromIpaddress is not None and fromUser is None:
            raise Exception("cannot handle if given IP address but not user")
        if toIpaddress is not None and toUser is None:
            raise Exception("cannot handle if given IP address but not user")
        if fromIpaddress is not None and toIpaddress is not None:
            raise Exception("cannot handle copying from IP address to IP address")
        #
        self._fromUser = fromUser
        self._fromIpaddress = fromIpaddress
        self._fromPath = fromPath
        if self._fromIpaddress is not None:
            self._fromSpecification = self._fromUser + "@" + self._fromIpaddress + ":" + self._fromPath
        else:
            self._fromSpecification = self._fromPath
        self._toUser = toUser
        self._toIpaddress = toIpaddress
        self._toPath = toPath
        if self._toIpaddress is not None:
            self._toSpecification = self._toUser + "@" + self._toIpaddress + ":" + self._toPath
        else:
            self._toSpecification = self._toPath
        self._pwd = pwd
        if self._pwd:
            if type(pwdPrompt) != SshCommand._regexType:
                self._pwdPromptRegex = re.compile(re.escape(pwdPrompt))
            else:
                # a regular expression object already
                self._pwdPromptRegex = pwdPrompt
            if type(acceptPrompt) != SshCommand._regexType:
                self._acceptPromptRegex = re.compile(re.escape(acceptPrompt))
            else:
                # a regular expression object already
                self._acceptPromptRegex = acceptPrompt
        self._output = ""
        self._returncode = None
        #
        # fork and connect child to a pseudo-terminal
        self._pid, self._fd = pty.fork()
        if self._pid == 0:
            # in child process
            os.execvp("scp", ["scp", self._fromSpecification, self._toSpecification])
        else:
            # in parent process
            if self._pwd:
                # if given a password then apply
                promptedForPassword = False
                outputTillPrompt = ""
                # look for password prompt
                while not promptedForPassword:
                    try:
                        newOutput = os.read(self._fd, 1024)
                        if not len(newOutput):
                            # end has been reached
                            # was raise Exception("unexpected end of output from scp")
                            raise Exception("failing to connect for scp\n" + 
                                            outputTillPrompt)
                        # ssh has been observed returning "\r\n" for newline, but we want "\n"
                        newOutput = SshCommand._crLfRegex.sub("\n", newOutput)
                        outputTillPrompt += newOutput
                        if self._acceptPromptRegex.search(outputTillPrompt):
                            # e.g. "Are you sure you want to continue connecting (yes/no)? "
                            raise Exception("cannot proceed unless having accepted host key\n" + 
                                            outputTillPrompt + 
                                            "\nE.g. invoke SshCommand.acceptKnownHostKey({0}).".format(self._ipaddress))
                        if self._pwdPromptRegex.search(outputTillPrompt):
                            # e.g. "10.123.45.67's password: "
                            promptedForPassword = True
                    except EnvironmentError:
                        # e.g. "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @" and closing
                        raise Exception("failing to connect for scp\n" + 
                                        outputTillPrompt)
                os.write(self._fd, self._pwd + "\n")
            # look for output
            endOfOutput = False
            outputSincePrompt = ""
            try:
                while not endOfOutput:
                    try:
                        newOutput = os.read(self._fd, 1024)
                        if len(newOutput):
                            outputSincePrompt += newOutput
                        else:
                            # end has been reached
                            endOfOutput = True
                    except EnvironmentError as e:
                        # some ideas maybe at http://bugs.python.org/issue5380
                        if e.errno == 5: # errno.EIO:
                            # seen when pty closes OSError: [Errno 5] Input/output error
                            endOfOutput = True
                        else:
                            # we accept what we got so far, for now
                            endOfOutput = True
            finally:
                # remove any leading space (maybe there after "password:" prompt) and
                # remove first newline (is there after entering password and "\n")
                self._output = re.sub(r"^\s*?\n(.*)$", r"\1", outputSincePrompt)
                #
                # get returncode
                try:
                    ignorePidAgain, waitEncodedStatusIndication = os.waitpid(self._pid, 0)
                    if os.WIFEXITED(waitEncodedStatusIndication):
                        # normal exit(status) call
                        self._returncode = os.WEXITSTATUS(waitEncodedStatusIndication)
                        # raise an exception if there is a reason
                        exceptionMessage = ""
                        if self._returncode:
                            exceptionMessage += "returncode: " + str(self._returncode)
                        if exceptionMessage:
                            commandDescription = "scp from:\n\t" + self._fromSpecification
                            commandDescription += "\nto:\n\t" + self._toSpecification
                            exceptionMessage = commandDescription + "\n" + exceptionMessage
                            exceptionMessage += "\noutput:\n" + self._output
                            raise ScpCommandException(exceptionMessage)
                    else:
                        # e.g. os.WIFSIGNALED or os.WIFSTOPPED
                        self._returncode = -1
                        raise ScpCommandException("scp did not exit normally")
                except OSError:
                    # supposedly can occur
                    self._returncode = -1
                    raise ScpCommandException("scp did not exit normally")

    @property
    def output(self):
        """Collected output string of scp command.
        
        May contain extraneous leading or trailing newlines and whitespace."""
        return self._output

    @property
    def returncode(self):
        """Returncode of command or 255 if an scp error occurred.
        
        Could be None."""
        return self._returncode

if __name__ == "__main__":
    SystemRequirements.commandsRequiredByImplementations([ScpCommand], verbose=True)
    #
    import shutil
    import tempfile
    from nrvr.util.time import Timestamp
    _testDir = os.path.join(tempfile.gettempdir(), Timestamp.microsecondTimestamp())
    os.mkdir(_testDir, 0755)
    try:
        _sendDir = os.path.join(_testDir, "send")
        os.mkdir(_sendDir, 0755)
        _exampleFile1 = os.path.join(_sendDir, "example1.txt")
        with open(_exampleFile1, "w") as outputFile:
            outputFile.write("this is an example\n" * 1000000)
        # fictional 10.123.45.67
#        _scpExample1 = ScpCommand(fromPath=_exampleFile1,
#                                  toUser="root", toIpaddress="10.123.45.67", toPath="~/example1.txt",
#                                  pwd="redwood")
#        print "returncode=" + str(_scpExample1.returncode)
#        print "output=" + _scpExample1.output
#        _scpExample2 = ScpCommand(fromUser="root", fromIpaddress="10.123.45.67", fromPath="/etc/hosts",
#                                  toPath=_exampleFile1,
#                                  pwd="redwood")
#        print "returncode=" + str(_scpExample2.returncode)
#        print "output=" + _scpExample2.output
#        with open(_exampleFile1, "r") as inputFile:
#            _exampleFile1Content = inputFile.read()
#        print "content=\n" + _exampleFile1Content
    finally:
        shutil.rmtree(_testDir)

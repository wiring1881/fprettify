import re
import string
from collections import deque
try:
    from cStringIO import StringIO
except ImportError:
    from io import StringIO

USE_PARSE_RE = re.compile(
    r" *use +(?P<module>[a-zA-Z_][a-zA-Z_0-9]*)(?P<only> *, *only *:)? *(?P<imports>.*)$",
    flags=re.IGNORECASE)
VAR_DECL_RE = re.compile(r" *(?P<type>integer(?: *\* *[0-9]+)?|logical|character(?: *\* *[0-9]+)?|real(?: *\* *[0-9]+)?|complex(?: *\* *[0-9]+)?|type) *(?P<parameters>\((?:[^()]+|\((?:[^()]+|\([^()]*\))*\))*\))? *(?P<attributes>(?: *, *[a-zA-Z_0-9]+(?: *\((?:[^()]+|\((?:[^()]+|\([^()]*\))*\))*\))?)+)? *(?P<dpnt>::)?(?P<vars>[^\n]+)\n?", re.IGNORECASE)  # $

OMP_DIR_RE = re.compile(r"^\s*(!\$omp)", re.IGNORECASE)
OMP_RE = re.compile(r"^\s*(!\$)", re.IGNORECASE)


class CharFilter(object):
    """
    An iterator to wrap the iterator returned by `enumerate`
    and ignore comments and characters inside strings
    """

    def __init__(self, it):
        self._it = it
        self._instring = ''

    def __iter__(self):
        return self

    def __next__(self):
        """ python 3 version"""
        pos, char = next(self._it)
        if not self._instring and char == '!':
            raise StopIteration

        # detect start/end of a string
        if char == '"' or char == "'":
            if self._instring == char:
                self._instring = ''
            elif not self._instring:
                self._instring = char

        if self._instring:
            return self.__next__()

        return (pos, char)

    def next(self):
        """ python 2 version"""
        pos, char = self._it.next()
        if not self._instring and char == '!':
            raise StopIteration

        # detect start/end of a string
        if char == '"' or char == "'":
            if self._instring == char:
                self._instring = ''
            elif not self._instring:
                self._instring = char

        if self._instring:
            return self.next()

        return (pos, char)


class InputStream(object):
    """
    Class to read logical Fortran lines from a Fortran file.
    """

    def __init__(self, infile):
        self.line_buffer = deque([])
        self.infile = infile
        self.line_nr = 0

    def nextFortranLine(self):
        """Reads a group of connected lines (connected with &, separated by newline or semicolon)
        returns a touple with the joined line, and a list with the original lines.
        Doesn't support multiline character constants!
        """
        lineRe = re.compile(
            # $
            r"(?:(?P<preprocessor>#.*\n?)| *(&)?(?P<core>(?:!\$|[^&!\"']+|\"[^\"]*\"|'[^']*')*)(?P<continue>&)? *(?P<comment>!.*)?\n?)",
            re.IGNORECASE)
        joinedLine = ""
        comments = []
        lines = []
        continuation = 0

        while 1:
            if not self.line_buffer:
                line = self.infile.readline().replace("\t", 8 * " ")
                self.line_nr += 1
                # convert OMP-conditional fortran statements into normal fortran statements
                # but remember to convert them back
                is_omp_conditional = False
                omp_indent = 0
                if OMP_RE.match(line):
                    omp_indent = len(line) - len(line.lstrip(' '))
                    line = OMP_RE.sub('', line, count=1)
                    is_omp_conditional = True
                line_start = 0
                for pos, char in CharFilter(enumerate(line)):
                    if char == ';' or pos + 1 == len(line):
                        self.line_buffer.append(omp_indent * ' ' + '!$' * is_omp_conditional +
                                                line[line_start:pos + 1])
                        omp_indent = 0
                        is_omp_conditional = False
                        line_start = pos + 1
                if(line_start < len(line)):
                    # line + comment
                    self.line_buffer.append('!$' * is_omp_conditional +
                                            line[line_start:])

            if self.line_buffer:
                line = self.line_buffer.popleft()

            if not line:
                break

            lines.append(line)
            m = lineRe.match(line)
            if not m or m.span()[1] != len(line):
                # FIXME: does not handle line continuation of
                # omp conditional fortran statements
                # starting with an ampersand.
                raise SyntaxError("unexpected line format:" + repr(line))
            if m.group("preprocessor"):
                if len(lines) > 1:
                    raise SyntaxError(
                        "continuation to a preprocessor line not supported " + repr(line))
                comments.append(line)
                break
            coreAtt = m.group("core")
            if OMP_RE.match(coreAtt) and joinedLine.strip():
                # remove omp '!$' for line continuation
                coreAtt = OMP_RE.sub('', coreAtt, count=1).lstrip()
            joinedLine = joinedLine.rstrip("\n") + coreAtt
            if coreAtt and not coreAtt.isspace():
                continuation = 0
            if m.group("continue"):
                continuation = 1
            if line.lstrip().startswith('!') and not OMP_RE.search(line):
                comments.append(line.rstrip('\n'))
            elif m.group("comment"):
                comments.append(m.group("comment"))
            else:
                comments.append('')
            if not continuation:
                break
        return (joinedLine, comments, lines)



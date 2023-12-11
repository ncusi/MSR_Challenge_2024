import copy
import re
from difflib import SequenceMatcher, get_close_matches
from operator import itemgetter

from unidiff import PatchSet, PatchedFile, Hunk
from joblib import Parallel, delayed


def to_str(self):
    content = "".join(str(line) for line in self)
    return content


def hunk_to_str(self):
    """Extract string to be used for comparison with Hunk from unidiff.PatchSet

    This `self` hunk can synthetic Hunk created as container for unidiff.patch.Line's
    by the get_hunk_images() function.

    :param Hunk self: modified block of a file, may be synthetic
    :return: all lines of changes in hunk, with their prefix removed,
        concatenated into a single string
    :rtype: str
    """
    return "".join(line.value for line in self)


# monkey-patching Hunk
Hunk.to_str = hunk_to_str


def get_close_matches2(word, pos, n, cutoff = 0.5):
    match_size = 0
    match_word = ""

    for p in pos:
        m = SequenceMatcher(a=word, b=p).find_longest_match()
        if m.size > match_size:
            match_size = m.size
            match_word = p

    if match_size == 0 or (match_size / len(word)) < cutoff:
        return None

    return match_word


def get_close_matches3(word, pos, n, cutoff):
    match_size = 0
    match_word = ""

    for p in pos:
        m = SequenceMatcher(a=word, b=p)
        if m.quick_ratio() > match_size:
            r = m.ratio()
            if r > match_size:
                match_size = r
                match_word = p
            if r >= cutoff and len(match_word.strip()) > 0:
                return match_word

    if match_size == 0 or match_size < cutoff or len(match_word.strip()) == 0:
        return None

    return match_word


class CompareBase:
    def __init__(self, image, lines=False):
        self.pos = {"r": 0, "p": None}
        self.lines = lines
        if lines:
            self.pos["l"] = None

        self.rnewline = re.compile(r"\n")

        self.image = image
        self.simage = image.to_str()

        # sequence matcher and maximal match
        self.seq_match = None
        self.chats = []

    def __repr__(self):
        return str(self.pos)


class CompareLines(CompareBase):
    def __init__(self, image, lines=False, threshold=0.5):
        super().__init__(image, lines)
        self.threshold = threshold

    def compare(self, b, pno, lno=None):
        a = self.simage
        self.chats.append(b)

    # alternate version
    def final(self):
        chatl = []
        for chat in self.chats:
            #chatl.extend([s.strip() for s in chat.splitlines() if len(s.strip())>0])
            chatl.extend(chat.splitlines())

        ret = []

        for line in self.image:
            if len(str(line).strip())==0:
                continue

            m = get_close_matches3(str(line), chatl, 1, self.threshold)
            if m:
                ret.append(line.diff_line_no)

        return ret


class CompareLinesFragmentThreshold(CompareLines):
    def __init__(self, image, lines=False):
        super().__init__(image, lines)

    def compare(self, b, pno, lno=None):

        a = self.simage
        s = SequenceMatcher(None, a, b)

        # Threshold version
        if s.real_quick_ratio() >= 0.1 and s.quick_ratio() >= 0.1 and s.ratio() >= 0.1:
            self.seq_match = s
            self.chats.append(b)


class CompareTopFragments(CompareBase):
    # Work in progress
    def __init__(self, image, lines=False):
        super().__init__(image, lines)

    def compare(self, b, pno, lno=None):
        a = self.simage
        s = SequenceMatcher(None, a, b)

        # Max version
        if s.real_quick_ratio() >= self.pos["r"] and s.quick_ratio() >= self.pos["r"]:
            r = s.ratio()
            if r > self.pos["r"]:
                self.pos = {"r": r, "p": pno}
                self.seq_match = s
                self.chat = b
                if self.lines:
                    self.pos["l"] = lno


class CompareFragments(CompareBase):
    def __init__(self, image, lines=False):
        """Construct a CompareFragments

        :param Hunk image: pre-image or post-image hunk of commit diff;
            unidiff.Hunk is monkey-patched to have `to_str` attribute (method).
        :param bool lines: whether to remember `lno` in compare()
        """
        # noinspection PyTypeChecker
        super().__init__(image, lines)
        self.chat = ""

    def compare(self, b, pno, lno=None):
        """Compare pre-image or post-image hunk against ChatGPT text

        :param str b: text of element of ChatGPT conversation
            (prompt, or answer, or code block)
        :param int pno: index into 'Conversations' list of 'ChatgptSharing'
        :param int or None lno: index into 'ListOfCode' list of conversation
        :rtype: None
        """
        a = self.simage
        s = SequenceMatcher(None, a, b)

        # Max version
        if s.real_quick_ratio() >= self.pos["r"] and s.quick_ratio() >= self.pos["r"]:
            r = s.ratio()
            if r > self.pos["r"]:
                self.pos = {"r": r, "p": pno}
                self.seq_match = s
                self.chat = b
                if self.lines:
                    self.pos["l"] = lno

    # Max version
    def final(self, cutoff=0.5,
              ret_chat_line_no=False, ret_score=False):
        """Final result of sequence of compare()'s

        :param float cutoff: a float in the range [0, 1], default 0.5.
            Lines from ChatGPT that don’t score at least that similar to patch line
            are ignored.
        :param bool ret_chat_line_no: whether to add chat_line_no to output
        :param bool ret_score: whether to add similarity score to output
        :return: list of diff line numbers of those lines in the `self.image` Hunk
            that have at least 1 matching line with at least `cutoff` similarity
            in one of compared chat fragments (prompt, or answer, or code block),
            or list of tuples that include diff line number as first element
        :rtype: list[int] or list[tuple[int, int]] or list[tuple[int, float]] or list[tuple[int, int, float]]
        """
        if not self.seq_match:
            return []

        chat_lines = self.chat.splitlines()
        ret = []

        for line in self.image:
            line_s = getattr(line, 'value', str(line)).rstrip('\n')
            # skip empty lines; str(line) for adding empty line is '+\n', so it does not match ''
            if not line_s:
                continue
            m = get_close_matches(line_s, chat_lines, n=1, cutoff=cutoff)
            if m:
                res = line.diff_line_no
                if ret_chat_line_no:
                    chat_line_no = [line_no
                                    for line_no, line in enumerate(chat_lines)
                                    if line == m[0]][0]
                    res = (res, chat_line_no)
                if ret_score:
                    # following source of get_close_matches() in difflib library
                    # https://github.com/python/cpython/blob/main/Lib/difflib.py
                    # s.set_seq2(word), s.set_seq1(possibilities[i])
                    s = SequenceMatcher(a=m[0], b=line_s)  # a ≡ s.set_seq1, b ≡ s.set_seq2
                    r = s.ratio()
                    if isinstance(res, tuple):
                        res = (*res, r)
                    else:
                        res = (res, r)

                ret.append(res)

        return ret


def get_hunk_images(hunk):
    """Split chunk into pre-image and post-image Hunk

    Second Hunk in the returned tuple includes only added files;
    all the other lines are returned in first Hunk in the tuple.
    Note that those returned synthesized chunks may lack correct
    header information - they are used only as containers for patch.Line.

    :param Hunk hunk: original part of diff, includes added, removed, and context lines
    :return: "preimage" and "postimage" hunks
    :rtype: (Hunk, Hunk)
    """
    postimage = Hunk()
    preimage = Hunk()
    for line in hunk:
        lc = copy.copy(line)

        if line.is_added:
            postimage.append(lc)
        else:
            preimage.append(lc)

    return preimage, postimage


def get_max_coverage(image, conv, Compare = CompareFragments,
                     ret_chat_line_no=False, ret_score=False):
    """

    Returns dict with the following structure:
        {
            "P": <comparison of `hunk` with "Prompt">,
            "A": <comparison of `hunk` with "Answer">,
            "L": <comparison of `hunk` with "ListOfCode">,
        }

    :param Hunk image: modified block of file, changed by diff;
        might be synthesized hunk returned by :func:`get_hunk_images`
    :param dict conv: "Conversation" part of `ChatgptSharing` structure,
        see https://github.com/NAIST-SE/DevGPT/blob/main/README.md#conversations
    :param type[CompareBase] Compare: compare class to use
    :param bool ret_chat_line_no: whether to add chat_line_no to output
    :param bool ret_score: whether to add similarity score to output
    :return:
    :rtype: dict[str, list[int]]
    """
    # iterate over conversation
    m_answer = Compare(image)
    m_prompt = Compare(image)
    m_loc = Compare(image, lines=True)

    for pno, prompt in enumerate(conv):
        a, b = prompt["Prompt"], prompt["Answer"]

        m_prompt.compare(a, pno)
        m_answer.compare(b, pno)

        for lno, loc in enumerate(prompt["ListOfCode"]):
            m_loc.compare(loc["Content"], pno, lno)

    return {
        # among 'Prompt'
        "P": m_prompt.final(ret_chat_line_no=ret_chat_line_no, ret_score=ret_score),
        "p": m_prompt.pos,
        # among 'Answer'
        "A": m_answer.final(ret_chat_line_no=ret_chat_line_no, ret_score=ret_score),
        "a": m_answer.pos,
        # among 'ListOfCode'
        "L": m_loc.final(ret_chat_line_no=ret_chat_line_no, ret_score=ret_score),
        "l": m_loc.pos,
    }


def diff_to_conversation_file(file, conv, debug=False, compare=CompareFragments):
    """

    :param PatchedFile file: file updated by `diff`, it is a list of Hunk's
    :param dict conv: ChatGPT link mention as `ChatgptSharing` structure,
        see https://github.com/NAIST-SE/DevGPT/blob/main/README.md#chatgptsharing
    :param bool debug: return also data about individual files
    :param type[CompareBase] compare: compare class to use
    :return:
    rtype dict[str, dict[str, int | set] | dict]
    """

    ret = {
        "ALL": {
            "coverage": 0,
            "all": 0,
            "lines": set(),
            "preimage": set(),
            "preimage_all": 0,
            "preimage_coverage": 0,
        }
    }

    fn = file.path
    if debug:
        ret["FILE"] = (file.source_file, file.target_file)
        ret["PATH"] = fn

    for i, hunk in enumerate(file):
        preimage, postimage = get_hunk_images(hunk)

        pre = get_max_coverage(preimage, conv["Conversations"], Compare=compare,
                               ret_chat_line_no=debug, ret_score=debug)
        post = get_max_coverage(postimage, conv["Conversations"], Compare=compare,
                                ret_chat_line_no=debug, ret_score=debug)

        # Only 'Answer' and 'ListOfCode' for post
        ret_lines = []
        ret_lines.extend(map(itemgetter(0), post["A"]) if debug else post["A"])
        ret_lines.extend(map(itemgetter(0), post["L"]) if debug else post["L"])
        ret_lines = set(ret_lines)
        # TODO: check how many remove lines from 'P'
        # that are exactly the same as in 'A' + 'L'.
        # this has to be done on source lines and may be expensive

        # ret_lines = set(ret_lines).union(set(post['P']))
        ret["ALL"]["coverage"] += len(ret_lines)
        #ret["ALL"]["all"] += len([l for l in postimage if len(str(l).strip())>0])
        ret["ALL"]["all"] += len(postimage)
        ret["ALL"]["lines"] = ret["ALL"]["lines"].union(ret_lines)

        # Only 'Prompt' for pre
        pre_set = set(map(itemgetter(0), pre["P"]) if debug else pre["P"])
        ret["ALL"]["preimage"] = ret["ALL"]["preimage"].union(pre_set)
        ret["ALL"]["preimage_coverage"] += len(pre_set)
        ret["ALL"]["preimage_all"] += len(preimage)

        if debug:
            if "HUNKS" not in ret:
                ret["HUNKS"] = {}

            ret["HUNKS"][i] = {
                "pre": pre,
                "post": post,
                "lines": list(ret_lines),
            }

    return ret


def diff_to_conversation(diff, conv, debug=False, compare = CompareFragments):
    """

    :param PatchSet diff: result of running GitRepo.unidiff(), it is a list of PatchedFile's
    :param dict conv: ChatGPT link mention as `ChatgptSharing` structure,
        see https://github.com/NAIST-SE/DevGPT/blob/main/README.md#chatgptsharing
    :param bool debug: passed down to :func:`diff_to_conversation_file`
    :param type[CompareBase] compare: compare class to use
    :return:
    :rtype: dict[str, dict[str, int | list]]
    """
    ret = {}

    ret["ALL"] = {"coverage": 0, "all": 0, "lines": [], 'preimage':[], 'preimage_all':0, 'preimage_coverage':0}
    if debug:
        ret["ALL"]["debug"] = True

    if "Conversations" not in conv:
        return ret

    ret_list =[]
    #for file in diff:
    #    ret_list.append(diff_to_conversation_file(file, diff, conv, debug, compare))
    ret_list = Parallel(n_jobs=-1)(delayed(diff_to_conversation_file)(file, conv, debug, compare) for file in diff)

    for r in ret_list:
        ret["ALL"]["coverage"] += r['ALL']["coverage"]
        ret["ALL"]["all"] += r['ALL']["all"]

        ret["ALL"]["preimage_coverage"] += r['ALL']["preimage_coverage"]
        ret["ALL"]["preimage_all"] += r['ALL']["preimage_all"]

        ret["ALL"]["lines"].extend(r['ALL']["lines"])
        ret["ALL"]["preimage"].extend(r['ALL']["preimage"])

        if debug:
            # r might be {} if there were errors
            if 'PATH' in r:
                filename = r['PATH']
                if 'FILES' not in ret:
                    ret['FILES'] = {}
                ret['FILES'][filename] = {
                    key: value
                    for key, value in r.items()
                    if key in ['FILE', 'HUNKS']
                }

    return ret

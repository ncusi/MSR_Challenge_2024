import copy
import re
from difflib import SequenceMatcher, get_close_matches

from unidiff import Hunk
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
        super().__init__(image, lines)
        self.chat = ""

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

    # Max version
    def final(self, cutoff=0.5, ret_chat_line_no=False):
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

                ret.append(res)

        return ret


def get_hunk_images(hunk):
    postimage = Hunk()
    preimage = Hunk()
    for line in hunk:
        lc = copy.copy(line)

        if line.is_added:
            postimage.append(lc)
        else:
            preimage.append(lc)

    return preimage, postimage


def get_max_coverage(image, conv, Compare = CompareFragments):
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

    return {"P": m_prompt.final(), "A": m_answer.final(), "L": m_loc.final()}


def diff_to_conversation_file(file, diff, conv, debug=False, compare = CompareFragments):

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

    fn = file.source_file

    if debug:
        ret[fn] = {}

    for i, hunk in enumerate(file):
        preimage, postimage = get_hunk_images(hunk)


        pre = get_max_coverage(preimage, conv["Conversations"], Compare=compare)
        post = get_max_coverage(postimage, conv["Conversations"], Compare=compare)

        ret_lines = []
        ret_lines.extend(post["A"])
        ret_lines.extend(post["L"])
        ret_lines = set(ret_lines)
        # TODO: check how many remove lines from 'P'
        # that are exactly the same as in 'A' + 'L'.
        # this has to be done on source lines and may be expensive

        # ret_lines = set(ret_lines).union(set(post['P']))
        ret["ALL"]["coverage"] += len(ret_lines)
        #ret["ALL"]["all"] += len([l for l in postimage if len(str(l).strip())>0])
        ret["ALL"]["all"] += len(postimage)
        ret["ALL"]["lines"] = ret["ALL"]["lines"].union(ret_lines)

        ret["ALL"]["preimage"] = ret["ALL"]["preimage"].union(set(pre["P"])) # Only prompt for pre
        ret["ALL"]["preimage_coverage"] += len(pre["P"]) # Only prompt for pre
        ret["ALL"]["preimage_all"] += len(preimage)

        if debug:
            ret[fn][i] = {"pre": pre, "post": post}
            ret[fn][i]["lines"] = list(ret_lines)

    return ret


def diff_to_conversation(diff, conv, debug=False, compare = CompareFragments):
    ret = {}

    ret["ALL"] = {"coverage": 0, "all": 0, "lines": [], 'preimage':[], 'preimage_all':0, 'preimage_coverage':0}

    if "Conversations" not in conv:
        return ret

    ret_list =[]
    #for file in diff:
    #    ret_list.append(diff_to_conversation_file(file, diff, conv, debug, compare))
    ret_list = Parallel(n_jobs=-1)(delayed(diff_to_conversation_file)(file, diff, conv, debug, compare) for file in diff)

    for r in ret_list:
        ret["ALL"]["coverage"] += r['ALL']["coverage"]
        ret["ALL"]["all"] += r['ALL']["all"]

        ret["ALL"]["preimage_coverage"] += r['ALL']["preimage_coverage"]
        ret["ALL"]["preimage_all"] += r['ALL']["preimage_all"]

        ret["ALL"]["lines"].extend(r['ALL']["lines"])
        ret["ALL"]["preimage"].extend(r['ALL']["preimage"])


    return ret

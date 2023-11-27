import copy
import json
import re
from difflib import SequenceMatcher, get_close_matches

import tqdm
from unidiff import Hunk


LINE_TYPE_CONTEXT = ' '

def to_str(self):
    content = ''.join(str(line) for line in self)
    return content

Hunk.to_str = to_str


def get_close_matches2(word, pos, n, cutoff):
    match_size = 0
    match_word = ""

    for p in pos:
        m = SequenceMatcher(a=word, b=p).find_longest_match()
        if m.size > match_size:
            match_size = m.size
            match_word = p
    
    if match_size == 0 or (match_size / len(word)) < 0.5:
        return None

    return match_word


class Compare:
    def __init__(self, image, lines = False):
        
        self.pos = {'r' : 0,  'p' : None}
        self.lines = lines
        if lines:
            self.pos['l'] = None
            
        self.rnewline = re.compile(r"\n")

        self.image = image
        self.simage = image.to_str()
        
        # sequence matcher and maximal match
        self.seq_match = None
        self.chats = []
    
    def compare(self, b, pno, lno = None):
        a = self.simage
        # s = SequenceMatcher(None, a, b)

        self.chats.append(b)
        
        # Max version
        # if s.real_quick_ratio() >= self.pos['r'] and s.quick_ratio() >= self.pos['r']:
        #     r = s.ratio()
        #     if  r > self.pos['r']:
                
        #         self.pos = {'r': r, 'p': pno}
        #         self.seq_match = s
        #         self.chat = b
        #         if self.lines:
        #             self.pos['l'] = lno

        # Alternate max version
        #         self.chats.append(b)
                

        # Threshold version
        # if s.real_quick_ratio() >= 0.1 and s.quick_ratio() >= 0.1 and s.ratio() >= 0.1:
        #     self.seq_match = s
        #     self.chats.append(b)


    # Max version 
    # def final(self):

    #     if not self.seq_match:
    #         return []
        
    #     chatl = self.chat.splitlines()
    #     ret = []
        
    #     for line in self.image:
    #         m = get_close_matches(str(line), chatl, 1, 0.6)
    #         if m:
    #             ret.append(line.diff_line_no)
        
    #     return ret


    # alternate version
    def final(self):

        # if not self.seq_match:
        #     return []
        
        chatl = []
        for chat in self.chats:
            chatl.extend(chat.splitlines())

        ret = []
        
        for line in self.image:
            #m = get_close_matches(str(line), chatl, 1, 0.5)
            m = get_close_matches2(str(line), chatl, 1, 0.5)
            if m:
                ret.append(line.diff_line_no)
        
        return ret

    
    def __repr__(self):
        return str(self.pos)

        
def get_hunk_images(hunk):
    postimage = Hunk()
    preimage = Hunk()
    for line in hunk:
        lc = copy.copy(line)
        lc.line_type = LINE_TYPE_CONTEXT
        
        if line.is_added:
            postimage.append(lc)
        else:
            preimage.append(lc)
            
    return preimage, postimage

def get_max_coverage(image, conv):

    # iterate over conversation
    m_anwser = Compare(image)
    
    m_prompt = Compare(image)
    
    m_loc = Compare(image, lines = True)
    
    for pno, prompt in enumerate(conv):
        a, b = prompt['Prompt'], prompt['Answer']

        m_prompt.compare(a, pno)
        m_anwser.compare(b, pno)

        for lno, loc in enumerate(prompt['ListOfCode']):
            m_loc.compare(loc['Content'], pno, lno)
    
    
    return {'P': m_prompt.final(), 'A': m_anwser.final(),  'L': m_loc.final()}


def diff_to_conversation(diff, conv, debug=False):
    ret = {}

    ret['ALL'] = {'coverage': 0, 'all': 0, 'lines': []}

    if 'Conversations' not in conv:
        return ret
        
    for file in diff:
        fn = file.source_file
        ret[fn] = {}

        for i, hunk in enumerate(file):
            preimage, postimage = get_hunk_images(hunk)
            
            pre = get_max_coverage(preimage, conv['Conversations'])
            post = get_max_coverage(postimage, conv['Conversations'])
            
            ret_lines = [] 
            ret_lines.extend(post['A'])
            ret_lines.extend(post['L'])
            ret_lines = set(ret_lines)
            # TODO: check how many remove lines from 'P' 
            # that are exactly the same as in 'A' + 'L'.
            # this has to be done on source lines and may be expensive 
            
            #ret_lines = set(ret_lines).union(set(post['P']))
            ret['ALL']['coverage'] += len(ret_lines)
            ret['ALL']['all'] += len(postimage)
            ret['ALL']['lines'].append(list(ret_lines))

            if debug:
                ret[fn][i] = {'pre': pre, 'post':post}
                ret[fn][i]['lines'] = list(ret_lines)
            
    return ret

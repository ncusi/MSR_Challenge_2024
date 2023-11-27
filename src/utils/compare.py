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
    
    def compare(self, b, pno, lno = None):
        a = self.simage
        s = SequenceMatcher(None, a, b)
        
        if s.real_quick_ratio() >= self.pos['r'] and s.quick_ratio() >= self.pos['r']:
            r = s.ratio()
            if  r > self.pos['r']:
                
                self.pos = {'r': r, 'p': pno}
                self.seq_match = s
                self.chat = b
                
                if self.lines:
                    self.pos['l'] = lno

    def final(self):

        if not self.seq_match:
            return []
        
        chatl = self.chat.splitlines()
        ret = []
        
        for line in self.image:
            m = get_close_matches(str(line), chatl, 1, 0.75)
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


def diff_to_conversation(diff, conversation):
    ret = {}
    if 'Conversations' not in conv:
        return ret
        
    for file in diff:
        fn = file.source_file
        ret[fn] = {}
        for i, hunk in enumerate(file):
            preimage, postimage = get_hunk_images(hunk)
            
            pre = get_max_coverage(preimage, conv['Conversations'])
            post = get_max_coverage(postimage, conv['Conversations'])
            
        ret[fn][i] = {'pre': pre, 'post':post}
        ret_lines = [] 
        ret_lines.extend(post['A'])
        ret_lines.extend(post['L'])
        # TODO: check how many remove lines from 'P' 
        # that are exactly the same as in 'A' + 'L'.
        # this has to be done on source lines and may be expensive 
        
        #ret_lines = set(ret_lines).union(set(post['P']))
        ret[fn][i]['lines']=list(ret_lines)
        
            
    return ret


if __name__ == "__main__":
    # with open("20230914_074826_pr_sharings.json") as f:
    #     data = json.load(f)

    # chats = []

    # for source in tqdm.tqdm(data['Sources']):
    #     for conv in source['ChatgptSharing']:
    #         if 'Conversations' in conv and (True or source['URL'] in diffs):
    #             k = list(diffs.keys())[0]
    #             chats.append(diff_to_conversation(diffs[k], conv))

import json
import textwrap
import unittest
from operator import itemgetter
from pathlib import Path

from unidiff import PatchSet

from src.utils.compare import get_hunk_images, get_max_coverage, CompareFragments


class CompareTestCase(unittest.TestCase):
    def test_get_hunk_images(self):
        # https://github.com/X3msnake/revoscan-frame-player/commit/1e5a13a96cfcc6c409af4729d9a795160a682b42
        raw_patch = textwrap.dedent(r"""
        diff --git a/helpers/dph2video_display_230830.py b/helpers/dph2video_display_230830.py
        index 8edcdce..8a9e352 100644
        --- a/helpers/dph2video_display_230830.py
        +++ b/helpers/dph2video_display_230830.py
        @@ -12,18 +12,36 @@ if not dph_files:
             input("\n\t Press enter to exit;")
             exit()
        
        +
        +
         print("\n\t................................................................................")
         print("\n\t                                                                                ")
         print("\n\t   ESC: exits the script                                                        ")
         print("\n\t                                                                                ")
         print("\n\t - This script loops trough the dph files in the same folder as this py.        ")
         print("\n\t - Video is being saved while you see it run and is output to dph_output.mp4    ")
        -print("\n\t - The file will be in the same folder as this script                           ")
        +print("\n\t - The file will be in the same folder as this script                         \n")
         print("\n\t..............................................................................\n")
        
         # Define width and height for the output video frames
        -width = 640
        -height = 400
        +img = np.fromfile(dph_files[0], dtype=np.uint16)
        +img_size = img.size
        +
        +target_sizes = {
        +    64000: (320, 200),
        +    256000: (640, 400)
        +}
        +
        +if img_size in target_sizes:
        +    width, height = target_sizes[img_size]
        +else:
        +    # Calculate width and height based on the image size
        +    # You can adjust this calculation according to your requirements
        +    ratio = img_size / 64000  # Adjust the divisor as needed
        +    width = int(320 * ratio)   # Adjust the base width as needed
        +    height = int(200 * ratio)  # Adjust the base height as needed
        +
        +print(f" \t   Raw depth capture: {width}x{height}")
        
         # Create a VideoWriter object to save the output video
         fourcc = cv2.VideoWriter_fourcc(*'mp4v')"""[1:])
        parsed_patch = PatchSet(raw_patch)
        for patched_file in parsed_patch:
            for hunk in patched_file:
                preimage, postimage = get_hunk_images(hunk)
                self.assertEqual(len(hunk), len(preimage) + len(postimage),
                                 f"hunk = preimage + postimage for {hunk}")

    def test_get_max_coverage(self):
        # https://github.com/unknowntpo/playground-2022/commit/9bd6aa4742baec81d11913712f17e0da7517bdee
        raw_patch = Path('test_utils_compare-files/9bd6aa4742baec81d11913712f17e0da7517bdee.diff').read_text()
        parsed_patch = PatchSet(raw_patch)

        # https://chat.openai.com/share/58d110d6-4236-461c-b3c4-a8df6519c534
        # $ jq '.Sources[11].ChatgptSharing[0].Conversations' 20231012_230826_commit_sharings.json
        conv_json = Path('test_utils_compare-files/58d110d6-4236-461c-b3c4-a8df6519c534-conv.json').read_text()
        conv = json.loads(conv_json)

        # print(f"{len(conv)=}; {conv[0].keys()=}")
        # print(f"{parsed_patch=}")
        self.assertEqual(1, len(parsed_patch), "1 file in patch")
        for patched_file in parsed_patch:
            # print(f"{patched_file=}")
            self.assertEqual(1, len(patched_file), f"1 hunk in changed file '{patched_file.path}'")
            for hunk in patched_file:
                # print(f"{hunk=}")
                preimage, postimage = get_hunk_images(hunk)
                res = get_max_coverage(postimage, conv)

                # print("----- postimage.to_str():")
                # print(postimage.to_str())
                # print("--------------------")

                # from pprint import pprint
                # pprint(res)

                # print(f"{preimage=}, ({len(preimage)=})")
                # print(f"{postimage=}, ({len(postimage)=}):")
                # for patch_line in postimage:
                #     line_no = patch_line.diff_line_no
                #     print(f"{line_no:2}: "
                #           f"{'P' if line_no in res['P'] else ' '}"
                #           f"{'A' if line_no in res['A'] else ' '}"
                #           f"{'L' if line_no in res['L'] else ' '}"
                #           f" {patch_line}", end='')

                self.assertEqual(list(range(10, 20+1)), res['P'],
                                 # lines matching 'name: string, age: int , earn: int' pattern in "Prompt"
                                 "accidental match against postimage in 'Prompt'")
                self.assertEqual([], res['A'],
                                 "no match against postimage in 'Answer'")
                self.assertEqual(list(range(9, 21+1)), res['L'],
                                 # all lines are almost exact match, 1 to 1
                                 # (because we are comparing str(Line), which includes '+' prefix)
                                 "expected lines in postimage match against 'ListOfCode'")

    def test_compare(self):
        # https://github.com/unknowntpo/playground-2022/commit/9bd6aa4742baec81d11913712f17e0da7517bdee
        raw_patch = Path('test_utils_compare-files/9bd6aa4742baec81d11913712f17e0da7517bdee.diff').read_text()
        parsed_patch = PatchSet(raw_patch)

        # https://chat.openai.com/share/58d110d6-4236-461c-b3c4-a8df6519c534
        # $ jq '.Sources[11].ChatgptSharing[0].Conversations' 20231012_230826_commit_sharings.json
        conv_json = Path('test_utils_compare-files/58d110d6-4236-461c-b3c4-a8df6519c534-conv.json').read_text()
        conv = json.loads(conv_json)

        # from pprint import pprint

        # 1st and only hunk in 1st and only file in the patch
        _, postimage = get_hunk_images(parsed_patch[0][0])
        # print(f"{postimage=} ({len(postimage)=})")
        for compare_type in [CompareFragments]:
            with self.subTest("subclass of CompareBase", compare=compare_type):
                m_answer = compare_type(postimage)
                m_prompt = compare_type(postimage)
                m_loc = compare_type(postimage, lines=True)

                # print(f"{len(conv)=}")
                # print(f"before: {m_prompt=}, {m_answer=}, {m_loc=}")
                for pno, prompt in enumerate(conv):
                    m_prompt.compare(prompt["Prompt"], pno)
                    m_answer.compare(prompt["Answer"], pno)
                    # print(f".Conversation[{pno}]: {m_prompt=}, {m_answer=}")
                    # print(f" {prompt['Prompt'][0:12]=}... vs {m_prompt.chat[0:12]=}...")
                    # print(f" {prompt['Answer'][7:19]=}... vs {m_answer.chat[7:19]=}...")

                    # print(f"{len(prompt['ListOfCode'])=}")
                    for lno, loc in enumerate(prompt["ListOfCode"]):
                        m_loc.compare(loc["Content"], pno, lno)
                        # print(f" .Conversation[{pno}].ListOfCode[{lno}]: {m_loc=}")
                        # print(f"  {loc['Content'][0:9]}... vs {m_loc.chat[0:9]}...")

                # print(f"{m_prompt.final(ret_chat_line_no=True, ret_score=True)=}")
                # print(f".Conversation[{m_prompt.pos['p']}] with s.ratio()={m_prompt.pos['r']}")
                # print(f"{m_answer.final(ret_chat_line_no=True, ret_score=True)=}")
                # print(f".Conversation[{m_answer.pos['p']}] with s.ratio()={m_answer.pos['r']}")
                #
                # print(f"{m_loc.final(ret_chat_line_no=True, ret_score=True)=}")
                # print(f".Conversation[{m_loc.pos['p']}].ListOfCode[{m_loc.pos['l']}] with s.ratio()={m_loc.pos['r']}")

                m_prompt_final = m_prompt.final(ret_chat_line_no=True, ret_score=True)
                actual = list(map(itemgetter(0), m_prompt_final))
                expected = list(range(10, 20+1))

                self.assertEqual(expected, actual, "expected diff lines match against 'Prompt's")
                actual = list(map(itemgetter(1), m_prompt_final))
                expected = [4] * 11
                self.assertEqual(expected, actual, "expected chat lines of 'Prompt's matches against diff")

                # TODO: continue...


if __name__ == '__main__':
    unittest.main()

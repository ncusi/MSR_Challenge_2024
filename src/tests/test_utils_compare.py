import textwrap
import unittest

from unidiff import PatchSet

from src.utils.compare import get_hunk_images


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


if __name__ == '__main__':
    unittest.main()

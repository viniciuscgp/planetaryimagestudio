import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from planetary_studio.collections.exact_duplicates import scan_duplicates,remove_duplicates,skip_removed_duplicate,REGISTRY,pixels
from planetary_studio.sources.curiosity import DownloaderWorker
from planetary_studio.sources.perseverance import PerseveranceWorker
from planetary_studio.sources.archives import ArchiveWorker,ArchiveProvider
import tests.test_download_navigation as navigation


class ExactDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def save(self,name,array=None):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(array if array is not None else np.full((20,30,3),[70,100,130],np.uint8)).save(path)
        return path

    def test_one_pixel_and_transparency_and_16_bit_differences_are_kept(self):
        a=self.save('a.png');b=self.save('b.bmp')
        data=np.array(Image.open(a));data[0,0,0]+=1;changed=self.save('changed.png',data)
        rgba=np.dstack([np.array(Image.open(a)),np.full((20,30),255,np.uint8)])
        rgba[2,2,3]=254;alpha=self.save('alpha.png',rgba)
        low=np.full((20,30),1000,np.uint16)
        cv2.imwrite(str(self.root/'16a.png'),low);low[1,1]+=1;cv2.imwrite(str(self.root/'16b.png'),low)
        result=scan_duplicates(self.root)
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(set([result['groups'][0]['keeper'],*result['groups'][0]['copies']]),{a,b})
        self.assertNotEqual(pixels(self.root/'16a.png'),pixels(self.root/'16b.png'))
        self.assertTrue(changed.exists());self.assertTrue(alpha.exists())

    def test_annotations_even_corrupt_and_multiple_protected_copies_are_preserved(self):
        a=self.save('a.png');b=self.save('b.png');c=self.save('c.png');d=self.save('d.png')
        Path(str(a)+'.annotations.json').write_text('invalid but valuable')
        Path(str(b)+'.annotations.json').write_text(json.dumps({'undo':[{'drawings':[1]}]}))
        result=scan_duplicates(self.root,extra=[d])
        removed=remove_duplicates(self.root,result['groups'],extra=[d])
        self.assertEqual(removed['removed'],[c])
        self.assertTrue(all(p.exists() for p in (a,b,d)))
        self.assertEqual(Path(str(a)+'.annotations.json').read_text(),'invalid but valuable')
        self.assertTrue(skip_removed_duplicate(self.root,c))

    def test_recheck_annotations_pixels_and_failed_registry_write(self):
        a=self.save('a.png');b=self.save('b.png')
        groups=scan_duplicates(self.root)['groups']
        Path(str(b)+'.annotations.json').write_text('{}')
        self.assertEqual(remove_duplicates(self.root,groups)['removed'],[])
        Path(str(b)+'.annotations.json').unlink()
        with patch('planetary_studio.collections.exact_duplicates.write_registry',side_effect=OSError('disk full')):
            self.assertTrue(remove_duplicates(self.root,groups)['errors'])
        self.assertTrue(b.exists())
        data=np.array(Image.open(b));data[0,0,0]+=1;Image.fromarray(data).save(b)
        self.assertEqual(remove_duplicates(self.root,groups)['removed'],[])
        self.assertTrue(a.exists());self.assertTrue(b.exists())

    def test_registry_paths_are_scoped_and_missing_or_changed_keeper_allows_download(self):
        a=self.save('SOL1/a.png');b=self.save('SOL1/b.png');other=self.save('SOL2/b.png')
        groups=scan_duplicates(self.root,self.root/'SOL1')['groups']
        self.assertEqual(remove_duplicates(self.root,groups)['removed'],[b])
        self.assertTrue(skip_removed_duplicate(self.root,b))
        other.unlink();self.assertFalse(skip_removed_duplicate(self.root,other))
        self.save('SOL1/a.png',np.full((20,30,3),1,np.uint8))
        self.assertFalse(skip_removed_duplicate(self.root,b))
        a.unlink();self.assertFalse(skip_removed_duplicate(self.root,b))
        (self.root/REGISTRY).write_text('broken')
        self.assertFalse(skip_removed_duplicate(self.root,b))

    def test_cancellation_and_multiframe_leave_files_untouched(self):
        a=self.save('a.png');self.save('b.png')
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):scan_duplicates(self.root,cancel=event)
        Image.new('RGB',(20,20),'red').save(self.root/'multi.tif',save_all=True,append_images=[Image.new('RGB',(20,20),'blue')])
        self.assertTrue(scan_duplicates(self.root)['errors'])
        self.assertTrue(a.exists())

    def test_hash_collision_is_not_enough_and_paths_cannot_escape_collection(self):
        a=self.save('collection/a.png');b=self.save('collection/b.png')
        changed=np.array(Image.open(a));changed[0,0,0]+=1;self.save('collection/c.png',changed)
        class Collision:
            def hexdigest(self):return 'same-digest'
        with patch('planetary_studio.collections.exact_duplicates.hashlib.sha256',return_value=Collision()):
            groups=scan_duplicates(self.root/'collection')['groups']
        self.assertEqual(groups[0]['copies'],[b])
        outside=self.save('outside.png')
        group=scan_duplicates(self.root/'collection')['groups'][0]
        group['copies']=[outside]
        self.assertTrue(remove_duplicates(self.root/'collection',[group])['errors'])
        self.assertTrue(outside.exists())

    def test_curiosity_and_perseverance_skip_registered_names_without_network(self):
        self.save('SOL1/a.png');b=self.save('SOL1/b.png')
        remove_duplicates(self.root,scan_duplicates(self.root)['groups'])
        for kind in (DownloaderWorker,PerseveranceWorker):
            worker=kind(self.root,only_sol=1);self.addCleanup(worker.session.close)
            with patch.object(worker,'_latest_nasa_sol',return_value=1), \
                 patch.object(worker,'_prepare_catalog'), \
                 patch.object(worker,'_cached_sol_items',return_value=[{'x':1}]), \
                 patch.object(worker,'_image_url',return_value='https://example.org/b.png'), \
                 patch.object(worker,'_filename',return_value='b.png'), \
                 patch.object(worker,'_folder_for_sol',return_value=b.parent), \
                 patch.object(worker,'_download_file') as download:
                worker.run()
            download.assert_not_called()

    def test_archive_skip_registered_names(self):
        self.save('OBS/a.png');b=self.save('OBS/b.png')
        remove_duplicates(self.root,scan_duplicates(self.root)['groups'])
        class Provider(ArchiveProvider):
            def records(self,cursor):
                yield {'folder':'OBS','page':'https://example.org','urls':['https://example.org/b.png']},{'index':1}
        worker=ArchiveWorker(self.root,Provider,batch_size=1);self.addCleanup(worker.session.close)
        with patch.object(worker,'_download_file') as download:
            worker.run()
        download.assert_not_called();self.assertFalse(b.exists())


class DuplicateUITests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def test_review_protects_current_and_annotated_and_requires_explicit_remove(self):
        from planetary_studio.ui.duplicate_ui import DuplicateDialog
        from PySide6.QtTest import QTest
        first=self.image(1,'a.png');marked=self.image(1,'b.png');removable=self.image(1,'c.png')
        Path(str(marked)+'.annotations.json').write_text('{}')
        window=self.window();dialog=DuplicateDialog(window);self.addCleanup(dialog.close)
        dialog.start_scan()
        for _ in range(200):
            self.app.processEvents();time.sleep(.005)
            if dialog.worker is None:break
        self.assertIsNone(dialog.worker)
        self.assertTrue(all(p.exists() for p in (first,marked,removable)))
        selected=dialog.selected_groups()
        self.assertEqual([p for g in selected for p in g['copies']],[removable])
        dialog.start_remove()
        for _ in range(200):
            self.app.processEvents();time.sleep(.005)
            if dialog.worker is None:break
        self.assertEqual(dialog.removed,[removable]);self.assertTrue(first.exists());self.assertTrue(marked.exists())


if __name__=='__main__':unittest.main()

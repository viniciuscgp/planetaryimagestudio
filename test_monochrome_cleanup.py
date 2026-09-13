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

from exact_duplicates import REGISTRY,skip_removed_image,scan_duplicates,remove_duplicates
from monochrome_cleanup import is_monochrome,scan_monochrome,remove_monochrome
from sources.curiosity import DownloaderWorker
from sources.perseverance import PerseveranceWorker
from sources.archives import ArchiveWorker,ArchiveProvider
import test_download_navigation as navigation


class MonochromeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def save(self,name,array=None):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(array if array is not None else np.full((20,30,3),100,np.uint8)).save(path)
        return path

    def test_native_pixels_preserve_even_one_color_pixel_and_transparent_color(self):
        rgb=self.save('rgb.png')
        gray=self.save('gray.png',np.arange(600,dtype=np.uint16).reshape(20,30))
        jpeg=self.save('gray.jpg',np.full((20,30),128,np.uint8))
        color=np.full((20,30,3),100,np.uint8);color[0,0,0]+=1
        colored=self.save('color.png',color)
        rgba=np.dstack([color,np.zeros((20,30),np.uint8)])
        transparent=self.save('transparent.png',rgba)
        native=np.full((20,30,3),1000,np.uint16);native[0,0,0]+=1
        cv2.imwrite(str(self.root/'color16.png'),native)
        palette=Image.new('P',(20,30));palette.putpalette([100,100,101]+[0]*765);palette.save(self.root/'palette.png')
        result=scan_monochrome(self.root)
        self.assertEqual({p for g in result['groups'] for p in g['copies']},{rgb,gray,jpeg})
        for path in (colored,transparent,self.root/'color16.png',self.root/'palette.png'):
            self.assertFalse(is_monochrome(path));self.assertTrue(path.exists())

    def test_protection_and_persistent_names_scoped_to_folder(self):
        marked=self.save('SOL1/marked.png');pending=self.save('SOL1/pending.png');plain=self.save('SOL1/plain.png')
        other=self.save('SOL2/plain.png')
        Path(str(marked)+'.annotations.json').write_text('unreadable but protected')
        result=scan_monochrome(self.root,self.root/'SOL1',extra=[pending])
        self.assertEqual(result['checked'],3)
        removed=remove_monochrome(self.root,result['groups'],extra=[pending])
        self.assertEqual(removed['removed'],[plain])
        self.assertTrue(marked.exists());self.assertTrue(pending.exists());self.assertTrue(other.exists())
        self.assertTrue(skip_removed_image(self.root,plain))
        entry=json.loads((self.root/REGISTRY).read_text())['removed']['SOL1/plain.png']
        self.assertEqual(entry['reason'],'black_and_white')
        other.unlink();self.assertFalse(skip_removed_image(self.root,other))
        self.save('SOL1/plain.png');self.assertFalse(skip_removed_image(self.root,plain))

    def test_revalidation_and_registry_failure_keep_original(self):
        path=self.save('a.png');groups=scan_monochrome(self.root)['groups']
        with patch('monochrome_cleanup.write_registry',side_effect=OSError('disk full')):
            self.assertTrue(remove_monochrome(self.root,groups)['errors'])
        self.assertTrue(path.exists())
        Path(str(path)+'.annotations.json').write_text('{}')
        self.assertEqual(remove_monochrome(self.root,groups)['removed'],[])
        Path(str(path)+'.annotations.json').unlink()
        self.save('a.png',np.full((20,30,3),101,np.uint8))
        self.assertTrue(remove_monochrome(self.root,groups)['errors'])
        self.assertTrue(path.exists())
        (self.root/REGISTRY).write_text('broken')
        with self.assertRaises(ValueError):remove_monochrome(self.root,groups)
        self.assertTrue(path.exists())

    def test_cancel_errors_and_outside_paths_never_remove(self):
        path=self.save('collection/a.png');outside=self.save('outside.png')
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):scan_monochrome(self.root,cancel=event)
        (self.root/'broken.png').write_bytes(b'bad image')
        Image.new('L',(20,20)).save(self.root/'multi.tif',save_all=True,append_images=[Image.new('L',(20,20))])
        self.assertEqual(len(scan_monochrome(self.root)['errors']),2)
        groups=scan_monochrome(self.root/'collection')['groups']
        self.assertEqual(remove_monochrome(self.root/'collection',groups,cancel=event)['removed'],[])
        groups[0]['copies']=[outside]
        self.assertTrue(remove_monochrome(self.root/'collection',groups)['errors'])
        self.assertTrue(path.exists());self.assertTrue(outside.exists())

    def test_duplicate_and_monochrome_records_coexist(self):
        self.save('a.png');copy=self.save('b.png')
        remove_duplicates(self.root,scan_duplicates(self.root)['groups'])
        self.assertTrue(skip_removed_image(self.root,copy))
        remove_monochrome(self.root,scan_monochrome(self.root)['groups'])
        self.assertTrue(skip_removed_image(self.root,self.root/'a.png'))
        # Its identical keeper was explicitly excluded as monochrome too.
        self.assertTrue(skip_removed_image(self.root,copy))

    def test_downloaders_honor_explicit_monochrome_removal_offline(self):
        path=self.save('SOL1/b.png')
        remove_monochrome(self.root,scan_monochrome(self.root)['groups'])
        for kind in (DownloaderWorker,PerseveranceWorker):
            worker=kind(self.root,only_sol=1);self.addCleanup(worker.session.close)
            with patch.object(worker,'_latest_nasa_sol',return_value=1), \
                 patch.object(worker,'_prepare_catalog'), \
                 patch.object(worker,'_cached_sol_items',return_value=[{'x':1}]), \
                 patch.object(worker,'_image_url',return_value='https://example.org/b.png'), \
                 patch.object(worker,'_filename',return_value='b.png'), \
                 patch.object(worker,'_folder_for_sol',return_value=path.parent), \
                 patch.object(worker,'_download_file') as download:
                worker.run()
            download.assert_not_called()
        class Provider(ArchiveProvider):
            def records(self,cursor):
                yield {'folder':'SOL1','page':'https://example.org','urls':['https://example.org/b.png']},{'index':1}
        worker=ArchiveWorker(self.root,Provider,batch_size=1);self.addCleanup(worker.session.close)
        with patch.object(worker,'_download_file') as download:
            worker.run()
        download.assert_not_called();self.assertFalse(path.exists())


class MonochromeUITests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def wait_worker(self,dialog):
        deadline=time.monotonic()+4
        while dialog.worker is not None and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.005)
        self.assertIsNone(dialog.worker)

    def test_tools_menu_and_review_protect_annotations_current_and_unchecked(self):
        from duplicate_ui import DuplicateDialog
        from PySide6.QtCore import Qt
        paths=[self.image(1,name) for name in ('a.png','b.png','c.png','d.png')]
        for path in paths:Image.new('L',(80,60),100).save(path)
        Path(str(paths[1])+'.annotations.json').write_text('{}')
        window=self.window()
        menus={a.text():a.menu() for a in window.menuBar().actions()}
        self.assertIn(window.act_duplicates,menus['Ferramentas'].actions())
        self.assertIn(window.act_remove_monochrome,menus['Ferramentas'].actions())
        self.assertNotIn(window.act_duplicates,menus['Arquivo'].actions())
        self.assertEqual(window.act_duplicates.text(),'Remover duplicatas…')
        dialog=DuplicateDialog(window,monochrome=True);self.addCleanup(dialog.close)
        dialog.start_scan();self.wait_worker(dialog)
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual([p for g in dialog.selected_groups() for p in g['copies']],paths[2:])
        dialog.tree.topLevelItem(3).setCheckState(0,Qt.CheckState.Unchecked)
        dialog.start_remove();self.wait_worker(dialog)
        self.assertEqual(dialog.removed,[paths[2]])
        self.assertTrue(all(paths[i].exists() for i in (0,1,3)))


if __name__=='__main__':unittest.main()

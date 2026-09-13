import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from exact_duplicates import REGISTRY,write_registry
from restore_removed import validated_paths
from sources.curiosity import DownloaderWorker
from sources.perseverance import PerseveranceWorker
from sources.archives import ArchiveWorker,ArchiveProvider,STATE_FILE,collection_id
import test_download_navigation as navigation


class RestoreWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def download(self,key,url,path,name):
        Image.new('RGB',(12,12),'red').save(path)

    def test_rovers_only_restore_requested_names_and_preserve_existing_files(self):
        for kind in (DownloaderWorker,PerseveranceWorker):
            root=self.root/kind.__name__;root.mkdir()
            folder=root/'SOL001';folder.mkdir()
            existing=folder/'keep.png';Image.new('L',(10,10),45).save(existing)
            before=existing.read_bytes()
            worker=kind(root);worker.restore_paths=['SOL001/removed.png','SOL001/keep.png']
            finished=[];worker.finished.connect(finished.append)
            with patch.object(worker,'_latest_nasa_sol',return_value=2), \
                 patch.object(worker,'_prepare_catalog'), \
                 patch.object(worker,'_cached_sol_items',return_value=['removed.png','keep.png','unrelated.png']) as catalog, \
                 patch.object(worker,'_image_url',side_effect=lambda item:'https://example.org/'+item), \
                 patch.object(worker,'_filename',side_effect=lambda item,url,i:item), \
                 patch.object(worker,'_download_file',side_effect=self.download) as download:
                worker.run()
            self.assertEqual(download.call_count,1)
            self.assertEqual(catalog.call_args.args[0],1)
            self.assertEqual(existing.read_bytes(),before)
            self.assertTrue((folder/'removed.png').exists())
            self.assertFalse((folder/'unrelated.png').exists())
            self.assertIn('concluída',finished[-1])

    def test_archive_restore_exceeds_normal_batch_without_advancing_cursor(self):
        records={};paths=[]
        for i in range(12):
            folder=f'OBS{i}'
            records[str(collection_id(folder))]={'folder':folder,'page':'https://example.org',
                                                'urls':['https://example.org/a.png','https://example.org/other.png']}
            paths.append(folder+'/a.png')
        state={'cursor':{'page':99},'records':records}
        (self.root/STATE_FILE).write_text(json.dumps(state))
        worker=ArchiveWorker(self.root,ArchiveProvider,batch_size=1);worker.restore_paths=paths
        with patch.object(worker.provider,'records',create=True,side_effect=AssertionError('No whole-archive scan')), \
             patch.object(worker,'_download_file',side_effect=self.download) as download:
            worker.run()
        self.assertEqual(download.call_count,12)
        self.assertEqual(json.loads((self.root/STATE_FILE).read_text()),state)
        self.assertTrue(all((self.root/p).exists() for p in paths))

    def test_missing_urls_cancel_and_invalid_download_stay_pending(self):
        for scenario in ('missing','cancel','invalid'):
            worker=ArchiveWorker(self.root,ArchiveProvider);worker.restore_paths=['OBS/a.png']
            state={'records':{'1':{'folder':'OBS','urls':[] if scenario=='missing' else ['https://example.org/a.png']}}}
            (self.root/STATE_FILE).write_text(json.dumps(state))
            finished=[];worker.finished.connect(finished.append)
            if scenario=='cancel':worker.stop()
            with patch.object(worker,'_download_file',side_effect=lambda key,url,path,name:path.write_bytes(b'invalid')):
                worker.run()
            self.assertNotIn('concluída',finished[-1])
            self.assertFalse((self.root/'OBS/a.png').exists())
        with self.assertRaises(ValueError):validated_paths(self.root,['../outside.png'])


class RestoreUITests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def registry(self):
        write_registry(self.root,dict(version=1,removed={'SOL1/removed.png':dict(reason='black_and_white',pixel_sha256='a'*64)}))

    def test_action_removes_only_exclusion_metadata_and_launches_persisted_restore(self):
        original=self.image(1,'kept.png');before=original.read_bytes()
        sidecar=Path(str(original)+'.annotations.json');sidecar.write_text('{}')
        self.registry();window=self.window()
        with patch.object(window,'_save_state',return_value=True),patch.object(window,'_launch_downloader') as launch:
            window.act_restore_removed.trigger()
        launch.assert_called_once_with(restore_paths=['SOL1/removed.png'])
        self.assertFalse((self.root/REGISTRY).exists())
        self.assertTrue(sidecar.exists());self.assertEqual(original.read_bytes(),before)
        state=window._build_state(pending_resume=True)
        self.assertEqual(state['download']['mode'],'restore_removed')
        self.assertEqual(state['download']['restore_paths'],['SOL1/removed.png'])
        window._state=state
        with patch.object(window,'_launch_downloader') as launch:window._resume_saved_download()
        launch.assert_called_once_with(restore_paths=['SOL1/removed.png'])

    def test_save_failure_or_active_download_preserves_registry(self):
        from unittest.mock import Mock
        self.image(1,'kept.png');self.registry();window=self.window()
        with patch.object(window,'_save_state',return_value=False), \
             patch('app.QMessageBox.warning') as warning,patch.object(window,'_launch_downloader') as launch:
            window._restore_removed_images()
        warning.assert_called_once();launch.assert_not_called();self.assertTrue((self.root/REGISTRY).exists())
        with patch.object(window,'_download_thread',Mock()),patch('app.QMessageBox.information'), \
             patch.object(window,'_launch_downloader') as launch:
            window._restore_removed_images()
        launch.assert_not_called();self.assertTrue((self.root/REGISTRY).exists())


if __name__=='__main__':unittest.main()

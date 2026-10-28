"""Read only a unique, live, owned log hierarchy; never guess from flat rows."""
import ctypes
from ctypes import wintypes
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from proteus86 import native_simulation as adapter
from proteus86.native_simulation import find_log_control
from proteus86.simulation import Simulation,SimulationError


def row(hwnd,cls,title='',control_id=0,**extra):
    return dict(hwnd=hwnd,cls=cls,title=title,control_id=control_id,enabled=True,**extra)


class LogTree:
    """Mock Win32 itself so PID and real GetParent checks remain exercised."""
    def __init__(self):
        self.nodes={100:row(100,'LX_APPLN_DClkNoDC','circuit - Proteus 8 Professional - Simulation Errors')}
        self.parents={100:0};self.pids={100:77}
        self.top=[100]
        self.session=SimpleNamespace(pid=77,process=Mock(pid=77))
        self.session.process.poll.return_value=None
        self.session._ready=lambda:self.snapshot()[0]
        def wait(condition):
            found=condition()
            if not found:raise TimeoutError('test condition was not met')
            return found
        self.session._wait=wait

    def add(self,node,parent,pid=77):
        self.nodes[node['hwnd']]=node;self.parents[node['hwnd']]=parent;self.pids[node['hwnd']]=pid
        return node

    def debugger(self,base=200):
        self.add(row(base,'LX_APPLN_DClkNoDC','VSM Debugger',101),100)
        self.add(row(base+1,'LX_APPLN_DClkNoDC','Log Window',0),base)
        return self.add(row(base+2,'SysListView32','',1),base+1)

    def standalone_log(self,base=300):
        self.top.append(base)
        self.add(row(base,'LX_APPLN_DClkNoDC','Simulation Log',0),100)
        return self.add(row(base+1,'SysListView32','',1),base)

    def snapshot(self):
        # Deliberately flattened: matching sibling names are not parent proof.
        return [dict(self.nodes[hwnd],children=[dict(v) for k,v in self.nodes.items()
                   if k not in self.top and (hwnd==100 or self.parents[k]==hwnd)]) for hwnd in self.top]

    def __enter__(self):
        self.stack=ExitStack()
        def fake_pid(hwnd,out):
            ctypes.cast(out,ctypes.POINTER(wintypes.DWORD)).contents.value=self.pids.get(hwnd,0)
            return 1
        def text(hwnd,buffer,size):
            buffer.value=self.nodes[hwnd]['title'][:size-1];return len(buffer.value)
        def cls(hwnd,buffer,size):
            buffer.value=self.nodes[hwnd]['cls'][:size-1];return len(buffer.value)
        funcs={'GetWindowThreadProcessId':fake_pid,'GetParent':lambda h:self.parents.get(h,0),
               'GetWindowTextLengthW':lambda h:len(self.nodes[h]['title']),
               'GetWindowTextW':text,'GetClassNameW':cls,
               'GetDlgCtrlID':lambda h:self.nodes[h]['control_id'],'GetMenu':lambda h:1}
        self.api={name:self.stack.enter_context(patch.object(adapter.u,name,side_effect=fn))
                  for name,fn in funcs.items()}
        self.stack.enter_context(patch.object(adapter.native,'windows',side_effect=lambda pid:self.snapshot()))
        self.menus=self.stack.enter_context(patch.object(adapter.native,'menus',return_value=[]))
        return self

    def __exit__(self,*args):return self.stack.__exit__(*args)

    def find(self):return find_log_control(self.session,self.session._ready())

    def simulation(self):
        sim=Simulation.__new__(Simulation);sim.session=self.session;sim._command=Mock()
        return sim


class SimulationLogTests(unittest.TestCase):
    def test_existing_error_debugger_reads_spice_rows_without_menu_or_activation(self):
        with LogTree() as tree:
            control=tree.debugger();sim=tree.simulation()
            entries=[dict(text='[SPICE] singular matrix: check node #branch.',source='',image=0),
                     dict(text='Real Time Simulation failed to start.',source='',image=0)]
            with patch.object(adapter,'list_rows',return_value=entries) as read:
                self.assertEqual(sim.log_entries(),entries)
                self.assertFalse(sim.diagnostics()['passed'])
            self.assertEqual(read.call_args.args,(77,control['hwnd']))
            sim._command.assert_not_called();tree.menus.assert_not_called()
            inspected=[call.args[0] for call in tree.api['GetWindowThreadProcessId'].call_args_list]
            for handle in (100,200,201,202):self.assertIn(handle,inspected)

    def test_matching_flat_siblings_do_not_establish_real_parent_chain(self):
        with LogTree() as tree:
            control=tree.debugger();tree.parents[control['hwnd']]=100
            self.assertIsNone(tree.find())
            tree.parents[control['hwnd']]=201;tree.parents[201]=100
            self.assertIsNone(tree.find())

    def test_exact_native_control_signatures_are_required(self):
        for handle,field,value in ((202,'control_id',2),(202,'title','Other list'),
                                    (201,'control_id',5),(201,'cls','OtherClass'),
                                    (200,'control_id',102),(200,'title','Other debugger')):
            with self.subTest(handle=handle,field=field),LogTree() as tree:
                tree.debugger();tree.nodes[handle][field]=value
                self.assertIsNone(tree.find())

    def test_every_ancestor_must_still_belong_to_the_owned_pid(self):
        for handle in (100,200,201,202):
            with self.subTest(handle=handle),LogTree() as tree:
                tree.debugger();tree.pids[handle]=88
                with self.assertRaisesRegex(RuntimeError,'belongs to this Proteus session'):tree.find()

    def test_real_cycle_or_excessive_parent_depth_is_rejected(self):
        with LogTree() as tree:
            tree.debugger();tree.parents[200]=201
            with self.assertRaisesRegex(RuntimeError,'cycle'):tree.find()
        with LogTree() as tree:
            tree.debugger();tree.parents[200]=400
            for handle in range(400,470):tree.add(row(handle,'Intermediate'),handle+1)
            with self.assertRaisesRegex(RuntimeError,'depth limit'):tree.find()

    def test_detached_list_cannot_be_read_even_if_snapshot_includes_it(self):
        with LogTree() as tree:
            tree.debugger();tree.parents[200]=0
            self.assertIsNone(tree.find())

    def test_unknown_extra_native_layout_layer_is_not_inferred(self):
        with LogTree() as tree:
            tree.debugger();tree.add(row(250,'UnknownWrapper'),100);tree.parents[200]=250
            self.assertIsNone(tree.find())
        with LogTree() as tree:
            tree.standalone_log();tree.add(row(350,'UnknownWrapper'),100);tree.parents[300]=350
            self.assertIsNone(tree.find())

    def test_multiple_valid_debugger_logs_are_ambiguous_before_menu_or_read(self):
        with LogTree() as tree:
            tree.debugger();tree.debugger(210);sim=tree.simulation()
            with patch.object(adapter,'list_rows') as read:
                with self.assertRaisesRegex(RuntimeError,'Ambiguous'):sim.log_entries()
            read.assert_not_called();sim._command.assert_not_called();tree.menus.assert_not_called()

    def test_existing_verified_custom_class_log_is_read_without_menu(self):
        with LogTree() as tree:
            control=tree.standalone_log();sim=tree.simulation()
            with patch.object(adapter,'list_rows',return_value=[]) as read:
                self.assertEqual(sim.log_entries(),[])
            read.assert_called_once_with(77,control['hwnd']);sim._command.assert_not_called()

    def test_unobserved_standard_dialog_and_wrong_custom_log_signatures_are_rejected(self):
        for handle,field,value in ((300,'cls','#32770'),(300,'control_id',5),
                                    (301,'control_id',1001),(301,'title','Other list')):
            with self.subTest(handle=handle,field=field),LogTree() as tree:
                tree.standalone_log();tree.nodes[handle][field]=value
                self.assertIsNone(tree.find())

    def test_custom_log_list_requires_real_direct_parent_and_owned_main_chain(self):
        for parent in (0,100):
            with self.subTest(parent=parent),LogTree() as tree:
                control=tree.standalone_log();tree.parents[control['hwnd']]=parent
                self.assertIsNone(tree.find())
        with LogTree() as tree:
            tree.standalone_log();tree.parents[300]=0
            self.assertIsNone(tree.find())

    def test_two_custom_log_lists_or_debugger_plus_custom_log_are_ambiguous(self):
        with LogTree() as tree:
            tree.standalone_log();tree.add(row(302,'SysListView32','',1),300)
            with self.assertRaisesRegex(RuntimeError,'Ambiguous'):tree.find()
        with LogTree() as tree:
            tree.debugger();tree.standalone_log()
            with self.assertRaisesRegex(RuntimeError,'Ambiguous'):tree.find()

    def test_absent_log_falls_back_to_enabled_exact_menu(self):
        for path in ('Debug/1. Simulation Log','Graph/View Simulation Log'):
            with self.subTest(path=path),LogTree() as tree:
                sim=tree.simulation();sim._command.side_effect=lambda name:tree.standalone_log()
                tree.menus.return_value=[dict(path=path,enabled=True,command_id=17)]
                with patch.object(adapter,'list_rows',return_value=[{'text':'Ready'}]) as read:
                    self.assertEqual(sim.log_entries(),[{'text':'Ready'}])
                sim._command.assert_called_once_with(path);read.assert_called_once_with(77,301)

    def test_unavailable_disabled_and_duplicate_menu_fail_without_command(self):
        for menus in ([],[dict(path='Graph/View Simulation Log',enabled=False)],
                      [dict(path='Debug/1. Simulation Log',enabled=True)]*2):
            with self.subTest(menus=menus),LogTree() as tree:
                tree.menus.return_value=menus;sim=tree.simulation()
                with patch.object(adapter,'list_rows') as read:
                    with self.assertRaises(SimulationError):sim.log_entries()
                read.assert_not_called();sim._command.assert_not_called()

    def test_read_rechecks_identity_and_rejects_list_replacement(self):
        with LogTree() as tree:
            tree.debugger();sim=tree.simulation()
            def replace(*args):
                tree.parents[202]=0;tree.debugger(210)
                return [{'text':'Must not return this stale result'}]
            with patch.object(adapter,'list_rows',side_effect=replace):
                with self.assertRaisesRegex(SimulationError,'changed during read'):sim.log_entries()

    def test_read_rechecks_ancestor_pid_after_ipc(self):
        with LogTree() as tree:
            tree.debugger();sim=tree.simulation()
            def replace(*args):tree.pids[201]=88;return []
            with patch.object(adapter,'list_rows',side_effect=replace):
                with self.assertRaisesRegex(RuntimeError,'belongs to this Proteus session'):sim.log_entries()

    def test_control_detached_before_ipc_is_never_read(self):
        with LogTree() as tree:
            tree.debugger();sim=tree.simulation();calls=0
            def snapshot(pid):
                nonlocal calls
                calls+=1
                if calls==2:tree.parents[202]=0
                return tree.snapshot()
            with patch.object(adapter.native,'windows',side_effect=snapshot),patch.object(adapter,'list_rows') as read:
                with self.assertRaisesRegex(SimulationError,'changed during read'):sim.log_entries()
            read.assert_not_called();sim._command.assert_not_called()

    def test_main_identity_must_remain_the_same_after_ipc(self):
        with LogTree() as tree:
            tree.debugger();sim=tree.simulation()
            def replace(*args):
                tree.add(row(101,'LX_APPLN_DClkNoDC','circuit - Proteus 8 Professional'),0)
                tree.top=[101];tree.parents[200]=101
                return []
            with patch.object(adapter,'list_rows',side_effect=replace):
                with self.assertRaisesRegex(SimulationError,'main window changed'):sim.log_entries()

    def test_exited_process_changed_pid_and_unknown_main_profile_fail(self):
        with LogTree() as tree:
            tree.debugger();tree.session.process.poll.return_value=1
            with self.assertRaisesRegex(RuntimeError,'exited'):tree.find()
            tree.session.process.poll.return_value=None;tree.session.process.pid=78
            with self.assertRaisesRegex(RuntimeError,'identity changed'):tree.find()
            tree.session.process.pid=77;tree.nodes[100]['cls']='UnknownBuildWindow'
            with self.assertRaisesRegex(RuntimeError,'profile'):tree.find()

    def test_control_read_failure_is_not_hidden_by_menu_fallback(self):
        with LogTree() as tree:
            tree.debugger();sim=tree.simulation()
            with patch.object(adapter,'list_rows',side_effect=RuntimeError('native read failed')):
                with self.assertRaisesRegex(RuntimeError,'native read failed'):sim.log_entries()
            sim._command.assert_not_called()


if __name__=='__main__':unittest.main()

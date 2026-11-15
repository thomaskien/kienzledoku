import subprocess
import unittest
from unittest import mock
import systemd_start as start


def status(state='active',invocation='new',result='success'):
    return dict(ActiveState=state,SubState='running' if state=='active' else 'start',
                InvocationID=invocation,Result=result,LoadState='loaded')


class StartTests(unittest.TestCase):
    def run_case(self,states,result,restart=True):
        with mock.patch.object(start,'unit_state',side_effect=states), \
             mock.patch.object(start.subprocess,'run',return_value=result) as run, \
             mock.patch.object(start.time,'sleep'),mock.patch('builtins.print'):
            start.start_unit('kienzledoku-commander.service',restart=restart)
            return run.call_args_list

    def test_lost_dbus_reply_accepts_new_successful_invocation_without_restarting_twice(self):
        lost=mock.Mock(returncode=1,stderr='Warning! D-Bus connection terminated. Connection reset by peer')
        calls=self.run_case([status('inactive','old'),None,status('activating','new'),status()],lost)
        self.assertEqual(1,len(calls));self.assertEqual('restart',calls[0].args[0][1])

    def test_old_running_instance_does_not_mask_failed_restart(self):
        lost=mock.Mock(returncode=1,stderr='Connection reset by peer')
        with self.assertRaisesRegex(RuntimeError,'alte Instanz'):
            self.run_case([status(invocation='old'),status(invocation='old')],lost)

    def test_real_service_failure_is_not_ignored(self):
        lost=mock.Mock(returncode=1,stderr='Connection reset by peer')
        with self.assertRaisesRegex(RuntimeError,'Startfehler'):
            self.run_case([status('inactive','old'),status('failed',result='exit-code')],lost)

    def test_nontransport_error_is_not_retried(self):
        with self.assertRaisesRegex(RuntimeError,'Dienststart fehlgeschlagen'):
            self.run_case([status()],mock.Mock(returncode=1,stderr='Access denied'))

    def test_start_of_running_unit_issues_no_command(self):
        self.assertEqual([],self.run_case([status()],None,restart=False))

    def test_normal_restart_issues_one_command(self):
        self.assertEqual(1,len(self.run_case([status()],mock.Mock(returncode=0))))

    def test_lost_reply_is_bounded(self):
        with mock.patch.object(start,'unit_state',return_value=status('activating')), \
             mock.patch.object(start.subprocess,'run',return_value=mock.Mock(returncode=1,stderr='Connection reset by peer')), \
             mock.patch.object(start.time,'monotonic',side_effect=[0,601]),mock.patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'nicht bestätigt'):start.start_unit('synthetic',restart=True)

    def test_systemctl_timeout_also_reconciles_without_duplicate_restart(self):
        with mock.patch.object(start,'unit_state',side_effect=[status('inactive','old'),status()]), \
             mock.patch.object(start.subprocess,'run',side_effect=subprocess.TimeoutExpired('systemctl',600)) as run, \
             mock.patch('builtins.print'):
            start.start_unit('synthetic',restart=True);self.assertEqual(1,run.call_count)

if __name__=='__main__':unittest.main()

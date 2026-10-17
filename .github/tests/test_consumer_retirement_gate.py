"""A consumer retirement is major even when the signed implementation parent is unchanged."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retirement_adopter_gate', ROOT / '.github/scripts/adopter_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def native_git(repository, *args):
    return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false',
        '-c', 'core.hooksPath=/dev/null', '-C', str(repository), *args],
        stderr=subprocess.DEVNULL, text=True, timeout=10).strip()


class ConsumerRetirementGate(unittest.TestCase):
    def test_official_baseline_reads_receive_the_existing_workflow_credential(self):
        readers = {'shift-left.yml': ['adopter gate --', "recompose ludlow's party"],
                   'cut-release.yml': ['ticket 18 -- re-render'],
                   'propose-tier.yml': ["re-compose at today's date"],
                   'renovate-run.yml': ['run self-hosted renovate']}
        for workflow, names in readers.items():
            document = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())
            steps = [step for job in document['jobs'].values() for step in job['steps']]
            for name in names:
                with self.subTest(workflow=workflow, reader=name):
                    step = next(step for step in steps if step.get('name', '').startswith(name))
                    self.assertEqual(step.get('env', {}).get('GH_TOKEN'), '${{ github.token }}',
                                     'hosted gh has no ambient login for official baseline GETs')

    def test_unchanged_parent_does_not_hide_a_composed_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adopter, platform = root / 'adopter', root / 'platform'
            git = native_git
            for repository in (adopter, platform):
                repository.mkdir()
                git(repository, 'init', '-q')
                git(repository, 'config', 'user.name', 'synthetic test')
                git(repository, 'config', 'user.email', 'fixture@example.invalid')
            (platform / 'fixture').write_text('no real release or price\n')
            git(platform, 'add', '.')
            git(platform, 'commit', '-qm', 'synthetic parent')
            parent = git(platform, 'rev-parse', 'HEAD')
            git(platform, 'tag', 'v5.0.0')
            (adopter / 'gitops/platform').mkdir(parents=True)
            (adopter / 'gitops/platform/platform-pin.yaml').write_text(
                f'kind: GitRepository\nmetadata: {{name: platform}}\nspec:\n  ref:\n    tag: v5.0.0\n    commit: {parent}\n')
            (adopter / 'composed').mkdir()
            evidence = adopter / 'composed/evidence.json'
            evidence.write_text(json.dumps({'members': [{'version': v} for v in ('5.0.0', '6.0.0', '7.0.0')]}))
            git(adopter, 'add', '.')
            git(adopter, 'commit', '-qm', 'synthetic before')
            before = git(adopter, 'rev-parse', 'HEAD')
            evidence.write_text(json.dumps({'members': [{'version': '7.0.0'}]}))
            git(adopter, 'add', '.')
            git(adopter, 'commit', '-qm', 'synthetic retirement without authorization')
            after = git(adopter, 'rev-parse', 'HEAD')
            code, comment = gate.run(adopter, platform, before, after, 'unused', 'unused',
                                     composed_base_ref=before, composed_head_ref=after)
            self.assertEqual(code, 1, 'unreviewed retirement escaped the major refusal')
            self.assertIn('**major**', comment)
            self.assertIn('5.0.0', comment)
            self.assertIn('6.0.0', comment)


class RetirementReporting(unittest.TestCase):
    """Real gate/Git and a refusing process fixture, not a signed admission receipt."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adopter, self.platform, self.tools = [self.root / name for name in ('adopter', 'platform', 'tools')]
        self.tools.mkdir()
        for repository in (self.adopter, self.platform):
            repository.mkdir()
            native_git(repository, 'init', '-q')
            native_git(repository, 'config', 'user.name', 'synthetic test')
            native_git(repository, 'config', 'user.email', 'fixture@example.invalid')
        (self.platform / 'fixture').write_text('unsigned native fixture, not a publisher release\n')
        native_git(self.platform, 'add', '.')
        native_git(self.platform, 'commit', '-qm', 'Synthetic implementation')
        parent = native_git(self.platform, 'rev-parse', 'HEAD')
        for tag in ('v2.0.0', 'v2.0.1'):
            native_git(self.platform, 'tag', tag)
        self.reply, self.called = self.root / 'reader-reply.json', self.root / 'reader-called.json'
        self.reply.write_text(json.dumps({'exit': 1, 'body': {
            'admitted': False, 'reason': 'one reviewed consumer retirement must name exactly one publisher'}}))
        runner = self.adopter / '.github/scripts/platform-tools.py'
        runner.parent.mkdir(parents=True)
        runner.write_text('import json, pathlib, sys\n'
            'assert "retirement-check" in sys.argv[1:], "unexpected operation"\n'
            f'pathlib.Path({str(self.called)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            f'reply = json.loads(pathlib.Path({str(self.reply)!r}).read_text())\n'
            'print(reply.get("stdout", json.dumps(reply["body"])))\n'
            'raise SystemExit(reply["exit"])\n')
        pin = self.adopter / 'gitops/platform/platform-pin.yaml'
        pin.parent.mkdir(parents=True)
        evidence = self.adopter / 'composed/evidence.json'
        evidence.parent.mkdir()
        for tag, versions in [('v2.0.0', ['2.0.1', '4.0.0']), ('v2.0.1', ['4.0.0'])]:
            pin.write_text('kind: GitRepository\nmetadata: {name: platform}\nspec:\n  ref:\n'
                           f'    tag: {tag}\n    commit: {parent}\n')
            evidence.write_text(json.dumps({'members': [{'version': version} for version in versions]}))
            native_git(self.adopter, 'add', '.')
            native_git(self.adopter, 'commit', '-qm', 'Synthetic ' + tag)
            if tag == 'v2.0.0':
                self.before = native_git(self.adopter, 'rev-parse', 'HEAD')
        self.after = native_git(self.adopter, 'rev-parse', 'HEAD')

    def run_gate(self, new_ref=None):
        return gate.run(self.adopter, self.platform, self.before, new_ref or self.after,
                        'unused fixture identity', 'unused fixture issuer',
                        composed_base_ref=self.before, composed_head_ref=self.after,
                        retirement_tools_dir=self.tools)

    def test_reader_refusal_retains_the_completed_major(self):
        code, comment = self.run_gate()
        self.assertEqual(code, 1, 'reporting must not admit the refused retirement')
        self.assertIn('verified compiler refused the exact consumer retirement', comment)
        called = json.loads(self.called.read_text())
        self.assertIn('retirement-check', called)
        self.assertIn(self.before, called)
        self.assertIn(self.after, called)
        self.assertIn('| bump | **patch** | **major** |', comment,
                      'a later admission refusal must not erase the completed classification')

    def test_refusal_before_reading_the_window_has_no_classification(self):
        code, comment = self.run_gate(new_ref='missing-native-fixture-ref')
        self.assertEqual(code, 1)
        self.assertIn('platform-pin.yaml not found', comment)
        self.assertNotIn('| bump |', comment)
        self.assertFalse(self.called.exists(), 'an early refusal must not reach the reader')

    def test_incomplete_composition_does_not_report_a_retirement_classification(self):
        evidence = self.adopter / 'composed/evidence.json'
        evidence.write_text(json.dumps({'members': [{'version': version} for version in ('4.0.0', '9.0.0')]}))
        native_git(self.adopter, 'add', '.')
        native_git(self.adopter, 'commit', '-qm', 'Synthetic arrival without evidence')
        self.after = native_git(self.adopter, 'rev-parse', 'HEAD')
        code, comment = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn('9.0.0', comment)
        self.assertNotIn('| bump |', comment, 'a failed fold has no completed classification')
        self.assertFalse(self.called.exists())

    def test_malformed_admission_reply_still_refuses_with_the_completed_major(self):
        self.reply.write_text(json.dumps({'exit': 0, 'body': None, 'stdout': 'not-json'}))
        code, comment = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn('JSONDecodeError', comment)
        self.assertIn('| bump | **patch** | **major** |', comment)
        self.assertTrue(self.called.exists())

    def test_mismatched_admission_class_cannot_lower_or_accept_the_major(self):
        self.reply.write_text(json.dumps({'exit': 0, 'body': {
            'admitted': True, 'bump': 'none', 'retired': ['2.0.1']}}))
        code, comment = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn('retirement does not match the computed major removal', comment)
        self.assertIn('| bump | **patch** | **major** |', comment)
        self.assertTrue(self.called.exists())


if __name__ == '__main__':
    unittest.main()

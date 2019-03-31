# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os

from pex.executor import Executor
from pex.interpreter import PythonInterpreter

from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.backend.python.interpreter_selection_utils import (PY_3, PY_27,
                                                                   skip_unless_python3_present,
                                                                   skip_unless_python27_present)
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class InterpreterSelectionIntegrationTest(PantsRunIntegrationTest):

  testproject = 'testprojects/src/python/interpreter_selection'

  @classmethod
  def hermetic(cls):
    # We must set as true to ignore `PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS`
    # preconfiguring the interpreter_constraint. For example, in `ci.sh` we set
    # this environment variable to Python 3, which overrides any config defined
    # in the below tests.
    return True

  def test_cli_option_wins_compatibility_conflict(self):
    # Tests that targets with compatibility conflicts collide.
    binary_target = '{}:deliberately_conficting_compatibility'.format(self.testproject)
    pants_run = self._build_pex(binary_target)
    self.assert_success(pants_run, 'Failed to build {binary}.'.format(binary=binary_target))

  def test_conflict_via_config(self):
    # Tests that targets with compatibility conflict with targets with default compatibility.
    # NB: Passes empty `args` to avoid having the default CLI args override the config.
    config = {
        'python-setup': {
          'interpreter_constraints': ['CPython<2.7'],
        }
      }
    binary_target = '{}:echo_interpreter_version'.format(self.testproject)
    pants_run = self._build_pex(binary_target, config=config, args=[])
    self.assert_failure(pants_run,
                        'Unexpected successful build of {binary}.'.format(binary=binary_target))
    self.assertIn('Unable to detect a suitable interpreter for compatibilities',
                  pants_run.stdout_data)

  @skip_unless_python3_present
  def test_select_3(self):
    self._test_version(PY_3)

  @skip_unless_python27_present
  def test_select_27(self):
    self._test_version(PY_27)

  def _test_version(self, version):
    echo = self._echo_version(version)
    v = echo.split('.')  # E.g., 2.7.13.
    self.assertTrue(len(v) > 2, 'Not a valid version string: {}'.format(v))
    expected_components = version.split('.')
    self.assertEqual(expected_components, v[:len(expected_components)])

  def _echo_version(self, version):
    with temporary_dir() as distdir:
      config = {
        'GLOBAL': {
          'pants_distdir': distdir
        }
      }
      binary_name = 'echo_interpreter_version_{}'.format(version)
      binary_target = '{}:{}'.format(self.testproject, binary_name)
      pants_run = self._build_pex(binary_target, config, version=version)
      self.assert_success(pants_run, 'Failed to build {binary}.'.format(binary=binary_target))

      # Run the built pex.
      exe = os.path.join(distdir, binary_name + '.pex')
      proc = subprocess.Popen([exe], stdout=subprocess.PIPE)
      (stdout_data, _) = proc.communicate()
      return stdout_data.decode('utf-8')

  def _build_pex(self, binary_target, config=None, args=None, version=PY_27):
    # By default, Avoid some known-to-choke-on interpreters.
    if version == PY_3:
      constraint = '["CPython>=3.6,<4"]'
    else:
      constraint = '["CPython>=2.7,<3"]'
    args = list(args) if args is not None else [
          '--python-setup-interpreter-constraints={}'.format(constraint)
        ]
    command = ['binary', binary_target] + args
    return self.run_pants(command=command, config=config)

  def test_stale_interpreter_purge_integration(self):
    target = '{}:{}'.format(self.testproject, 'echo_interpreter_version')
    config = {
      'python-setup': {
        'interpreter_constraints': ['CPython>=2.7,<4'],
      }
    }
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(
        ["run", target],
        workdir=workdir,
        config=config
      )
      self.assert_success(pants_run)

      def _prepend_bad_interpreter_to_interpreter_path_file(path):
        with open(path, 'r') as fp:
          file_data = fp.readlines()
          file_data[0] = '/my/bogus/interpreter/python2.7'
        with open(path, 'w') as fp:
          fp.writelines(file_data)

      def _validate_good_interpreter_path_file(path):
        with open(path, 'r') as fp:
          lines = fp.readlines()
          binary = lines[0].strip()
          try:
            interpreter = PythonInterpreter.from_binary(binary)
            return True if interpreter else False
          except Executor.ExecutableNotFound:
            return False

      # Mangle interpreter.info.
      for path in glob.glob(os.path.join(workdir, 'pyprep/interpreter/*/interpreter.info')):
        _prepend_bad_interpreter_to_interpreter_path_file(path)

      pants_run = self.run_pants_with_workdir(
        ["run", target],
        workdir=workdir,
        config=config
      )
      self.assert_success(pants_run)
      for path in glob.glob(os.path.join(workdir, 'pyprep/interpreter/*/interpreter.info')):
        self.assertTrue(
          _validate_good_interpreter_path_file(path),
          'interpreter.info was not purged and repopulated properly: {}'.format(path)
        )

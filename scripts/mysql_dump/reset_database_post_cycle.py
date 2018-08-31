"""
Script for resetting the database by hand at the end of each cycle
"""
from __future__ import print_function

import subprocess
import getpass
import os
import re

# pylint:disable=import-error
import mysql.connector


# pylint:disable=too-many-instance-attributes,too-few-public-methods
# pylint:disable=too-many-arguments,attribute-defined-outside-init
class DatabaseReset(object):
    """
    Handles resetting the database after cycle
    """

    def __init__(self, latest_cycle, user, host='localhost', port='3306', password=''):
        # initial setup
        self.backup_directory = 'C:\\database_backup\\'
        self.user = user
        self.host = host
        self.port = port
        # optional as not required for local host occasionally
        self.password = password
        self.databases = 'autoreduction'

        self._validate(latest_cycle)

    def execute(self):
        """
        Execute the backup and data removal
        """
        # backup data
        self._backup_sql()
        # remove non-static data
        self._remove_non_static_data()

    def _validate(self, latest_cycle):
        self._validate_cycle_input(latest_cycle)
        self._validate_user_input()
        self._validate_backfile_location()

    def _validate_cycle_input(self, latest_cycle):
        if re.match(r'cycle_[0-9]([0-9])?_[0-9]', latest_cycle):
            self.cycle = latest_cycle
        else:
            raise RuntimeError('{} did not match the expected regex for a cycle. '
                               'Please use form: cycle_16_5'.format(latest_cycle))
        self.new_cycle_dir = self.backup_directory + self.cycle

    def _validate_user_input(self):
        if not self.user:
            raise RuntimeError('\'User\' for database required')
        if not self.host:
            raise RuntimeError('\'Host\' for database required')
        if not self.port:
            raise RuntimeError('\'Port\' for database required')
        else:
            try:
                int(self.port)
            except ValueError:
                raise RuntimeError('\'Port\' must be an integer')

    def _validate_backfile_location(self):
        # Make the directory if it doesn't exist
        if not os.path.exists(self.new_cycle_dir):
            os.makedirs(self.new_cycle_dir)

        self.backup_file = os.path.join(self.new_cycle_dir, self.cycle+'.sql')

        # Check we are not attempting to overwrite
        if os.path.isfile(self.backup_file):
            raise RuntimeError('Backup file with name: \'{}\' already exists.\n'
                               'Please rename it or remove it in order to allow '
                               'this script to execute. This script does not overwrite '
                               'for data security.'.format(self.backup_file))

    def _backup_sql(self):
        arguments = self._generate_argument_string()
        process = subprocess.Popen('mysqldump {0} --databases {1} --no-create-info'
                                   ' > {2}'.format(arguments, self.databases, self.backup_file),
                                   shell=True)
        process.communicate()

    def _generate_argument_string(self):
        args = '-u {}'.format(self.user)
        if self.password:
            args += ' --password={}'.format(self.password)
        if self.host:
            args += ' -h {}'.format(self.host)
        if self.port:
            args += ' -P {}'.format(self.port)
        return args

    def _remove_non_static_data(self):
        # Login to the database
        connection = mysql.connector.connect(user=self.user, password=self.password,
                                             host=self.host, database=self.databases)
        cursor = connection.cursor()

        # The list of tables to be deleted
        tables_to_delete = ['reduction_viewer_datalocation',
                            'reduction_viewer_experiment',
                            'reduction_viewer_notification',
                            'reduction_viewer_reductionrun',
                            'reduction_viewer_reductionlocation',
                            'reduction_viewer_setting',
                            'reduction_variables_instrumentvariable',
                            'reduction_variables_runvariable',
                            'reduction_variables_variable']

        # Turn off foreign key checks and safe updating momentarily
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("SET SQL_SAFE_UPDATES = 0")

        # Loop through each table and delete all of the entries
        for table in tables_to_delete:
            print('Deleting all from ' + table)
            cursor.execute("DELETE FROM autoreduction." + table)

        # Turn foreign key checks and safe updating
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        cursor.execute("SET SQL_SAFE_UPDATES = 1")

        # Commit our changes
        connection.commit()


def main():
    """
    Used to pass arguments via command line and then execute
    As this script should only ever be run on the machine with the database on it,
    we should use localhost:3306 to connect
    """
    cycle = raw_input('Current cycle name to backup: ')
    user = raw_input('Database user name: ')
    password = getpass.getpass('Database password (leave blank if none): ')
    print('Using \'localhost\' as database host')
    print('Using \'3306\' as database port')
    print('\n')
    cycle_reset = DatabaseReset(latest_cycle=cycle,
                                user=user,
                                host='localhost',
                                port='3306',
                                password=password)
    cycle_reset.execute()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as err:
        print(err)

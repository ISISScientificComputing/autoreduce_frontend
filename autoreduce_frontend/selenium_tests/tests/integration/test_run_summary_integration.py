# ############################################################################### #
# Autoreduction Repository : https://github.com/ISISScientificComputing/autoreduce
#
# Copyright &copy; 2021 ISIS Rutherford Appleton Laboratory UKRI
# SPDX - License - Identifier: GPL-3.0-or-later
# ############################################################################### #
"""Selenium tests for the runs summary page."""
import datetime
import pytz
import re

from django.urls import reverse

from autoreduce_frontend.selenium_tests.pages.run_summary_page import RunSummaryPage
from autoreduce_frontend.selenium_tests.pages.runs_list_page import RunsListPage
from autoreduce_frontend.selenium_tests.tests.base_tests import (AccessibilityTestMixin, BaseTestCase, FooterTestMixin,
                                                                 NavbarTestMixin)
from autoreduce_frontend.selenium_tests.utils import setup_external_services, submit_and_wait_for_result


class TestRunSummaryPageIntegration(BaseTestCase, FooterTestMixin, NavbarTestMixin, AccessibilityTestMixin):
    """
    Test cases for the InstrumentSummary page when the Rerun form is NOT
    visible.
    """

    fixtures = BaseTestCase.fixtures + ["run_with_one_variable"]
    accessibility_test_ignore_rules = {
        # https://github.com/ISISScientificComputing/autoreduce/issues/1267
        # https://github.com/ISISScientificComputing/autoreduce/issues/1268
        "duplicate-id-aria": "input, #run_description",
    }

    @classmethod
    def setUpClass(cls):
        """Start all external services."""
        super().setUpClass()
        cls.instrument_name = "TestInstrument"
        cls.rb_number = 1234567
        cls.run_number = 99999
        cls.data_archive, cls.queue_client, cls.listener = setup_external_services(cls.instrument_name, 21, 21)
        cls.data_archive.add_reduction_script(cls.instrument_name, """print('some text')""")
        cls.data_archive.add_reduce_vars_script(cls.instrument_name,
                                                """standard_vars={"variable1":"test_variable_value_123"}""")

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop all external services."""
        cls.queue_client.disconnect()
        cls.data_archive.delete()
        super().tearDownClass()

    def setUp(self) -> None:
        """
        Set up the RunSummaryPage and show the rerun panel before each test
        case.
        """
        super().setUp()
        self.page = RunSummaryPage(self.driver, self.instrument_name, 99999, 0)
        self.page.launch()
        # Click the toggle to show the rerun panel, otherwise the buttons in the
        # form are non interactive
        self.page.toggle_button.click()

    def test_submit_rerun_same_variables(self):
        """Test opening the submit page and clicking rerun."""
        result = submit_and_wait_for_result(self)
        assert len(result) == 2

        assert result[0].run_version == 0
        assert result[1].run_version == 1

        for run0_var, run1_var in zip(result[0].run_variables.all(), result[1].run_variables.all()):
            assert run0_var.variable == run1_var.variable

    def test_submit_rerun_changed_variable_arbitrary_value(self):
        """
        Test opening a submit page, changing a variable, and then submitting the
        run.
        """
        # Change the value of the variable field
        self.page.variable1_field = "the new value in the field"

        result = submit_and_wait_for_result(self)
        assert len(result) == 2

        assert result[0].run_version == 0
        assert result[1].run_version == 1

        for run0_var, run1_var in zip(result[0].run_variables.all(), result[1].run_variables.all()):
            # The value of the variable has been overwritten because it's the
            # same run number
            assert run0_var.variable == run1_var.variable

        assert result[1].run_variables.first().variable.value == "the new value in the field"

    def test_submit_rerun_after_clicking_reset_initial(self):
        """
        Test that submitting a run after changing the value and then clicking
        reset to initial values will correctly use the initial values.
        """
        # Change the value of the variable field
        self.page.variable1_field = "the new value in the field"

        self.page.reset_to_initial_values.click()
        result = submit_and_wait_for_result(self)
        assert len(result) == 2

        assert result[0].run_version == 0
        assert result[1].run_version == 1

        for run0_var, run1_var in zip(result[0].run_variables.all(), result[1].run_variables.all()):
            # The value of the variable has been overwritten because it's the
            # same run number
            assert run0_var.variable == run1_var.variable

        assert result[1].run_variables.first().variable.value == "value1"

    def test_submit_rerun_after_clicking_reset_current_script(self):
        """
        Test that submitting a run after clicking the reset to current script
        uses the values saved in the current script.
        """
        self.page.reset_to_current_values.click()
        result = submit_and_wait_for_result(self)

        assert len(result) == 2

        assert result[0].run_version == 0
        assert result[1].run_version == 1

        for run0_var, run1_var in zip(result[0].run_variables.all(), result[1].run_variables.all()):
            # The value of the variable has been overwritten because it's the
            # same run number
            assert run0_var.variable == run1_var.variable

        assert result[1].run_variables.first().variable.value == "test_variable_value_123"

    def test_submit_confirm_page(self):
        """Test that submitting a run leads to the correct page."""
        result = submit_and_wait_for_result(self)
        expected_url = reverse("run_confirmation", kwargs={"instrument": self.instrument_name})
        assert expected_url in self.driver.current_url
        # Wait until the message processing is complete before ending the test
        # otherwise the message handling can pollute the DB state for the next
        # test
        assert len(result) == 2
        # Check that the error is because of missing Mantid. If this fails then
        # something else in the reduction caused an error
        assert "Mantid" in result[1].admin_log

    def test_submit_respects_bst(self):
        """
        Test that a submitted run's datetime for when it was last updated
        adheres to British Summer Time in the runs list page.
        """
        submit_and_wait_for_result(self)
        runs_list_page = RunsListPage(self.driver, self.instrument_name)
        runs_list_page.launch()

        gmt = pytz.timezone("Europe/London")

        # Get the datetime of now
        now_datetime = gmt.localize(datetime.datetime.now())

        # Get the bottom run from the runs list page and cast it to datetime
        bottom_run_element = runs_list_page.get_created_from_table()[-1]
        temp = re.sub(' a.m.', 'AM', bottom_run_element)
        temp = re.sub(' p.m.', 'PM', temp)
        run_last_updated = datetime.datetime.strptime(temp, "%d/%m/%Y %I:%M%p")
        run_datetime = gmt.localize(run_last_updated)

        # Calculate the difference in minutes between the current time and the
        # time the run displays on the runs list page
        minutes_diff = (now_datetime - run_datetime).total_seconds() / 60.0

        # A minute diff more than 30 would indicate a wrong timezone
        assert minutes_diff < 30

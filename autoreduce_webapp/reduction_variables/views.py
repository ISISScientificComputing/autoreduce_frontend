from django.shortcuts import redirect
from django.core.context_processors import csrf
from django.template import RequestContext
from django.shortcuts import render_to_response
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseForbidden
from autoreduce_webapp.view_utils import login_and_uows_valid, render_with, has_valid_login, handle_redirect
from reduction_variables.models import InstrumentVariable, RunVariable
from reduction_variables.utils import InstrumentVariablesUtils, MessagingUtils
from reduction_viewer.models import Instrument, ReductionRun
from reduction_viewer.utils import StatusUtils, ReductionRunUtils

import logging, json
logger = logging.getLogger("app")

'''
    Imported into another view, thus no middleware
'''
def instrument_summary(request, instrument):
    instrument = Instrument.objects.get(name=instrument)
    
    current_variables, upcoming_variables_by_run, upcoming_variables_by_experiment = InstrumentVariablesUtils().get_current_and_upcoming_variables(instrument.name)

    # Create a nested dictionary for by-run
    upcoming_variables_by_run_dict = {}
    for variables in upcoming_variables_by_run:
        if variables.start_run not in upcoming_variables_by_run_dict:
            upcoming_variables_by_run_dict[variables.start_run] = {
                'run_start': variables.start_run,
                'run_end': 0, # We'll fill this in after
                'tracks_script': variables.tracks_script,
                'variables': [],
                'instrument': instrument,
            }
        upcoming_variables_by_run_dict[variables.start_run]['variables'].append(variables)

    # Move the upcoming vars into an ordered list
    upcoming_variables_by_run_ordered = []
    for key in sorted(upcoming_variables_by_run_dict):
        upcoming_variables_by_run_ordered.append(upcoming_variables_by_run_dict[key])
    sorted(upcoming_variables_by_run_ordered, key=lambda r: r['run_start'])
    
    # Fill in the run end numbers
    run_end = 0
    for run_number in sorted(upcoming_variables_by_run_dict.iterkeys(), reverse=True):
        upcoming_variables_by_run_dict[run_number]['run_end'] = run_end
        run_end = run_number-1

    try:
        next_variable_run_start = min(upcoming_variables_by_run_dict, key=upcoming_variables_by_run_dict.get)
    except ValueError:
        next_variable_run_start = 1
    
    current_vars = {
        'run_start': current_variables[0].start_run,
        'run_end': next_variable_run_start-1,
        'tracks_script': current_variables[0].tracks_script,
        'variables': current_variables,
        'instrument': instrument,
    }

    # Create a nested dictionary for by-experiment
    upcoming_variables_by_experiment_dict = {}
    for variables in upcoming_variables_by_experiment:
        if variables.experiment_reference not in upcoming_variables_by_experiment_dict:
            upcoming_variables_by_experiment_dict[variables.experiment_reference] = {
                'experiment': variables.experiment_reference,
                'variables': [],
                'instrument': instrument,
            }
        upcoming_variables_by_experiment_dict[variables.experiment_reference]['variables'].append(variables)

    # Move the upcoming vars into an ordered list
    upcoming_variables_by_experiment_ordered = []
    for key in sorted(upcoming_variables_by_experiment_dict):
        upcoming_variables_by_experiment_ordered.append(upcoming_variables_by_experiment_dict[key])
    sorted(upcoming_variables_by_experiment_ordered, key=lambda r: r['experiment'])

    context_dictionary = {
        'instrument': instrument,
        'current_variables': current_vars,
        'upcoming_variables_by_run': upcoming_variables_by_run_ordered,
        'upcoming_variables_by_experiment': upcoming_variables_by_experiment_ordered,
    }

    context_dictionary.update(csrf(request))

    return render_to_response('snippets/instrument_summary_variables.html', context_dictionary, RequestContext(request))

@login_and_uows_valid
def delete_instrument_variables(request, instrument, start=0, end=0, experiment_reference=None):
    instrument = Instrument.objects.get(name=instrument)
    if experiment_reference is None:
        InstrumentVariable.objects.filter(instrument=instrument, start_run=start).delete()
    else:
        InstrumentVariable.objects.filter(instrument=instrument, experiment_reference=experiment_reference).delete()

    return redirect('instrument_summary', instrument=instrument.name)

#@require_staff
@login_and_uows_valid
@render_with('instrument_variables.html')
def instrument_variables(request, instrument, start=0, end=0, experiment_reference=0):
    # Check the user has permission
    if not request.user.is_superuser and instrument not in request.session['owned_instruments']:
        raise PermissionDenied()
    
    instrument = Instrument.objects.get(name=instrument)
    if request.method == 'POST':
        # Truth value comes back as text so we'll compare it to a string of "True"
        is_run_range = request.POST.get("variable-range-toggle-value", "True") == "True"
        track_scripts = request.POST.get("track_script_checkbox") == "on"

        if is_run_range:
            start = request.POST.get("run_start", 1)
            end = request.POST.get("run_end", None)

            if request.POST.get("is_editing", '') == 'True':
                default_variables = InstrumentVariable.objects.filter(instrument=instrument, start_run=start)
            else:
                default_variables = InstrumentVariablesUtils().get_default_variables(instrument.name)

            # Remove any existing variables saved within the provided range
            if end and int(end) > 0:
                existing_variables = InstrumentVariable.objects.filter(instrument=instrument, start_run__gte=start, start_run__lte=end)
                # Create default variables for after the run end if they don't already exist
                if not InstrumentVariable.objects.filter(instrument=instrument, start_run=int(end)+1):
                    InstrumentVariablesUtils().set_default_instrument_variables(instrument.name, int(end)+1)
            else:
                existing_variables = InstrumentVariable.objects.filter(instrument=instrument, start_run__gte=start)
            for existing in existing_variables:
                existing.delete()
                
        else:
            experiment_reference = request.POST.get("experiment_reference_number", 1)

            if request.POST.get("is_editing", '') == 'True':
                default_variables = list(old_variables = InstrumentVariable.objects.filter(instrument=instrument, experiment_reference=experiment_reference))
            else:
                default_variables = InstrumentVariablesUtils().get_default_variables(instrument.name)

            existing_variables = InstrumentVariable.objects.filter(instrument=instrument, experiment_reference=experiment_reference)
            for existing in existing_variables:
                existing.delete()

                
        for default_var in default_variables:
            form_name = 'var-'
            if default_var.is_advanced:
                form_name += 'advanced-'
            else:
                form_name += 'standard-'
            form_name += default_var.sanitized_name()

            post_variable = request.POST.get(form_name, None)
            if post_variable:
                variable = InstrumentVariable( instrument = instrument
                                             , name = default_var.name
                                             , value = post_variable
                                             , is_advanced = default_var.is_advanced
                                             , type = default_var.type
                                             , tracks_script = track_scripts
                                             , help_text = default_var.help_text
                                             )
                if is_run_range:
                    variable.start_run = start
                else:
                    variable.experiment_reference = experiment_reference
            else:
                variable = default_var
                variable.pk = None
                variable.id = None
            variable.save()

        return redirect('instrument_summary', instrument=instrument.name)
        
        
    else:
        editing = (start > 0 or experiment_reference > 0)
        completed_status = StatusUtils().get_completed()
        processing_status = StatusUtils().get_processing()
        queued_status = StatusUtils().get_queued()

        try:
            latest_completed_run = ReductionRun.objects.filter(instrument=instrument, run_version=0, status=completed_status).order_by('-run_number').first().run_number
        except AttributeError:
            latest_completed_run = 0
        try:
            latest_processing_run = ReductionRun.objects.filter(instrument=instrument, run_version=0, status=processing_status).order_by('-run_number').first().run_number
        except AttributeError:
            latest_processing_run = 0

        if experiment_reference > 0:
            variables = InstrumentVariable.objects.filter(instrument=instrument,experiment_reference=experiment_reference)
        else:
            if not start and not end:
                try:
                    start = InstrumentVariable.objects.filter(instrument=instrument,start_run__lte=latest_completed_run ).order_by('-start_run').first().start_run
                except AttributeError :
                    start = 1
            if not start:
                start = 1
            if not end:
                end = 0
            variables = InstrumentVariable.objects.filter(instrument=instrument,start_run=start)
        
        if not editing:
            variables = InstrumentVariablesUtils().get_default_variables(instrument.name)
        elif not variables:
            # If no variables are saved, use the default ones from the reduce script
            editing = False
            InstrumentVariablesUtils().set_default_instrument_variables(instrument.name, start)
            variables = InstrumentVariable.objects.filter(instrument=instrument,start_run=start )

        standard_vars = {}
        advanced_vars = {}
        for variable in variables:
            if variable.is_advanced:
                advanced_vars[variable.name] = variable
            else:
                standard_vars[variable.name] = variable

        current_variables, upcoming_variables_by_run, upcoming_variables_by_experiment = InstrumentVariablesUtils().get_current_and_upcoming_variables(instrument.name)

        upcoming_run_variables = ','.join([str(i) for i in upcoming_variables_by_run.values_list('start_run', flat=True).distinct()])

        default_variables = InstrumentVariablesUtils().get_default_variables(instrument.name)
        default_standard_variables = {}
        default_advanced_variables = {}
        for variable in default_variables:
            if variable.is_advanced:
                default_advanced_variables[variable.name] = variable
            else:
                default_standard_variables[variable.name] = variable

        context_dictionary = {
            'instrument' : instrument,
            'last_instrument_run' : ReductionRun.objects.filter(instrument=instrument).exclude(status=StatusUtils().get_skipped()).order_by('-run_number')[0],
            'processing' : ReductionRun.objects.filter(instrument=instrument, status=processing_status),
            'queued' : ReductionRun.objects.filter(instrument=instrument, status=queued_status),
            'standard_variables' : standard_vars,
            'advanced_variables' : advanced_vars,
            'default_standard_variables' : default_standard_variables,
            'default_advanced_variables' : default_advanced_variables,
            'run_start' : start,
            'run_end' : end,
            'experiment_reference' : experiment_reference,
            'minimum_run_start' : max(latest_completed_run, latest_processing_run),
            'upcoming_run_variables' : upcoming_run_variables,
            'editing' : editing,
            'tracks_script' : variables[0].tracks_script,
        }
        context_dictionary.update(csrf(request))

        return context_dictionary

#@require_staff
@login_and_uows_valid
@render_with('submit_runs.html')
def submit_runs(request, instrument):
    # Check the user has permission
    if not request.user.is_superuser and instrument not in request.session['owned_instruments']:
        raise PermissionDenied()

    instrument = Instrument.objects.get(name=instrument)

    if request.method == 'GET':
        processing_status = StatusUtils().get_processing()
        queued_status = StatusUtils().get_queued()
        skipped_status = StatusUtils().get_skipped()

        last_run = ReductionRun.objects.filter(instrument=instrument).exclude(status=skipped_status).order_by('-run_number')[0]

        standard_vars = {}
        advanced_vars = {}

        default_variables = InstrumentVariablesUtils().get_default_variables(instrument.name)
        default_standard_variables = {}
        default_advanced_variables = {}
        for variable in default_variables:
            if variable.is_advanced:
                advanced_vars[variable.name] = variable
                default_advanced_variables[variable.name] = variable
            else:
                standard_vars[variable.name] = variable
                default_standard_variables[variable.name] = variable

        context_dictionary = {
            'instrument' : instrument,
            'last_instrument_run' : last_run,
            'processing' : ReductionRun.objects.filter(instrument=instrument, status=processing_status),
            'queued' : ReductionRun.objects.filter(instrument=instrument, status=queued_status),
            'standard_variables' : standard_vars,
            'advanced_variables' : advanced_vars,
            'default_standard_variables' : default_standard_variables,
            'default_advanced_variables' : default_advanced_variables,
        }
        context_dictionary.update(csrf(request))

        return context_dictionary


#@require_staff
@login_and_uows_valid
@render_with('snippets/edit_variables.html')
def current_default_variables(request, instrument):
    variables = InstrumentVariablesUtils().get_default_variables(instrument)
    standard_vars = {}
    advanced_vars = {}
    for variable in variables:
        if variable.is_advanced:
            advanced_vars[variable.name] = variable
        else:
            standard_vars[variable.name] = variable
    context_dictionary = {
        'instrument' : instrument,
        'standard_variables' : standard_vars,
        'advanced_variables' : advanced_vars,
    }
    context_dictionary.update(csrf(request))
    return context_dictionary

'''
    Imported into another view, thus no middleware
'''
def run_summary(request, run_number, run_version=0):
    reduction_run = ReductionRun.objects.get(run_number=run_number, run_version=run_version)
    variables = reduction_run.run_variables.all()

    standard_vars = {}
    advanced_vars = {}
    for variable in variables:
        if variable.is_advanced:
            advanced_vars[variable.name] = variable
        else:
            standard_vars[variable.name] = variable

    current_variables = InstrumentVariablesUtils().get_default_variables(reduction_run.instrument.name)
    current_standard_variables = {}
    current_advanced_variables = {}
    for variable in current_variables:
        if variable.is_advanced:
            current_advanced_variables[variable.name] = variable
        else:
            current_standard_variables[variable.name] = variable

    context_dictionary = {
        'run_number' : run_number,
        'run_version' : run_version,
        'standard_variables' : standard_vars,
        'advanced_variables' : advanced_vars,
        'default_standard_variables' : standard_vars,
        'default_advanced_variables' : advanced_vars,
        'current_standard_variables' : current_standard_variables,
        'current_advanced_variables' : current_advanced_variables,
        'instrument' : reduction_run.instrument,
    }
    context_dictionary.update(csrf(request))
    return render_to_response('snippets/run_variables.html', context_dictionary, RequestContext(request))

#@require_staff
@login_and_uows_valid
@render_with('run_confirmation.html')
def run_confirmation(request, instrument):
    if request.method != 'POST':
        return redirect('instrument_summary', instrument=instrument.name)
        
        
    # POST
    instrument = Instrument.objects.get(name=instrument)
    run_numbers = []

    if 'run_number' in request.POST:
        run_numbers.append(int(request.POST.get('run_number')))
    else:
        range_string = request.POST.get('run_range').split(',')
        # Expand list
        for item in range_string:
            if '-' in item:
                split_range = item.split('-')
                run_numbers.extend(range(int(split_range[0]), int(split_range[1])+1)) # because this is a range, the end bound is exclusive!
            else:
                run_numbers.append(int(item))
        # Make sure run numbers are distinct
        run_numbers = set(run_numbers)

    queued_status = StatusUtils().get_queued()
    queue_count = ReductionRun.objects.filter(instrument=instrument, status=queued_status).count()

    context_dictionary = {
        'runs' : [],
        'variables' : None,
        'queued' : queue_count,
    }


    # Check that RB numbers are the same
    rb_number = ReductionRun.objects.filter(instrument=instrument, run_number__in=run_numbers).values_list('experiment__reference_number', flat=True).distinct()
    if len(rb_number) > 1:
        context_dictionary['error'] = 'Runs span multiple experiment numbers (' + ','.join(str(i) for i in rb_number) + ') please select a different range.'

    # Check that RB numbers are allowed
    if not request.user.is_superuser:
        experiments_allowed = request.session['experiments_to_show'].get(instrument.name)
        if (experiments_allowed is not None) and (str(rb_number[0]) not in experiments_allowed):
            context_dictionary['error'] = "Permission denied. You do not have permission to request re-runs on the associated experiment number."

    # Quit on error.
    if 'error' in context_dictionary:
        return context_dictionary
            
    for run_number in run_numbers:
        old_reduction_run = ReductionRun.objects.filter(run_number=run_number).order_by('-run_version').first()

        use_current_script = request.POST.get('use_current_script', u"true").lower() == u"true"
        if use_current_script:
            script_text = InstrumentVariablesUtils().get_current_script_text(instrument.name)[0]
            default_variables = InstrumentVariablesUtils().get_variables_from_current_script(instrument.name)
        else:
            script_text = old_reduction_run.script
            default_variables = old_reduction_run.run_variables.all()
        
        new_variables = []

        for key,value in request.POST.iteritems():
            if 'var-' in key:
                name = None
                if 'var-advanced-' in key:
                    name = key.replace('var-advanced-', '').replace('-', ' ')
                    is_advanced = True
                if 'var-standard-' in key:
                    name = key.replace('var-standard-', '').replace('-', ' ')
                    is_advanced = False

                if name is not None:
                    default_var = next((x for x in default_variables if x.name == name), None)
                    if not default_var:
                        continue
                    if len(value) > InstrumentVariable._meta.get_field('value').max_length:
                        context_dictionary['error'] = 'Value given in ' + str(name) + ' is too long.'
                    variable = RunVariable( name = default_var.name
                                          , value = value
                                          , is_advanced = is_advanced
                                          , type = default_var.type
                                          , help_text = default_var.help_text
                                          )
                    new_variables.append(variable)

        if len(new_variables) == 0:
            context_dictionary['error'] = 'No variables were found to be submitted.'

            
        if 'error' in context_dictionary:
            return context_dictionary
        
        new_job = ReductionRunUtils().createRetryRun(old_reduction_run, script=script_text, variables=new_variables)

        try:
            MessagingUtils().send_pending(new_job)
            context_dictionary['runs'].append(new_job)
            context_dictionary['variables'] = new_variables
            
        except Exception as e:
            new_job.delete()
            context_dictionary['error'] = 'Failed to send new job. (%s)' % str(e)
            
    return context_dictionary

    
def preview_script(request, instrument, run_number=0, experiment_reference=0):
    # Can't use login decorator as need to return AJAX error message if fails
    if not has_valid_login(request):
        redirect_response = handle_redirect(request)
        if request.method == 'GET':
            return redirect_response
        else:
            error = {'redirect_url': redirect_response.url}
            return HttpResponseForbidden(json.dumps(error))
            
    # Check permissions
    if not request.user.is_superuser\
            and   ((experiment_reference and experiment_reference not in request.session['experiments'])\
                or (instrument           and instrument           not in request.session['owned_instruments'])):
        raise PermissionDenied()

    if request.method == 'GET':
        reduction_run = ReductionRun.objects.filter(run_number=run_number)
        if reduction_run:
            script_text = reduction_run[0].script
        else:
            script_text = InstrumentVariablesUtils().get_current_script_text(instrument)[0]

    elif request.method == 'POST':
        lookup_run_number = request.POST.get('run_number', None)
        lookup_run_version = request.POST.get('run_version', None)
        use_current_script = request.POST.get('use_current_script', default=u"false").lower() == u"true"

        reduction_run = ReductionRun.objects.filter(run_number=lookup_run_number, run_version=lookup_run_version)
        if reduction_run and not use_current_script:
            script_text = reduction_run[0].script
        else:
            script_text = InstrumentVariablesUtils().get_current_script_text(instrument)[0]
        
    
    response = HttpResponse(content_type='application/x-python')
    response['Content-Disposition'] = 'attachment; filename=reduce & reduce_vars.py'
    response.write(script_text)
    return response

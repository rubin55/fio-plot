#!/usr/bin/env python3
"""
This script is written to automate the process of running multiple
Fio benchmarks. The output of the benchmarks have been tailored to be used with
fio-plot.

You may also an older script already part of Fio if that better suits your needs:
https://github.com/axboe/fio/blob/master/tools/genfio
The output of this tool may not always fit with the file-name requirements of
fio-plot, depending on the graph type.
"""

import argparse
import sys
import os
import subprocess
import itertools
import datetime
import time
import shutil
from numpy import linspace
from pathlib import Path
import pprint


def convert_dict_vals_to_str(dictionary):
    """ Convert dictionary to format in uppercase, suitable as env vars.
    """
    return {k.upper(): str(v) for k, v in dictionary.items()}


def run_raw_command(command, env=None):
    result = subprocess.run(command, shell=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env)
    if result.returncode > 0:
        stdout = result.stdout.decode("UTF-8").strip()
        stderr = result.stderr.decode("UTF-8").strip()
        print(f"\nAn error occurred: {stderr} - {stdout}")
        sys.exit(1)

    return result


def run_command(settings, benchmark, command):
    """ This command sets up the environment that is used in conjunction
    with the Fio .ini job file.
    """
    output_directory = generate_output_directory(settings, benchmark)
    env = os.environ
    settings = convert_dict_vals_to_str(settings)
    benchmark = convert_dict_vals_to_str(benchmark)
    env.update(settings)
    env.update(benchmark)
    env.update({'OUTPUT': output_directory})
    run_raw_command(command, env)


def check_fio_version(settings):
    """ The 3.x series .json format is different from the 2.x series format.
    This breaks fio-plot, thus this older version is not supported.
    """

    command = ["fio", "--version"]
    result = run_raw_command(command).stdout
    result = result.decode("UTF-8").strip()
    if "fio-3" in result:
        return True
    elif "fio-2" in result:
        print(
            f"Your Fio version ({result}) is not compatible. Please use Fio-3.x")
        sys.exit(1)
    else:
        print("Could not detect Fio version.")
        sys.exit(1)


def make_directory(directory):
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
    except OSError:
        print(f"Failed to create {directory}")
        sys.exit(1)


def generate_output_directory(settings, benchmark):

    if benchmark['mode'] in settings['mixed']:
        directory = f"{settings['output']}/{os.path.basename(benchmark['target'])}/{benchmark['mode']}{benchmark['rwmixread']}/{benchmark['block_size']}"
    else:
        directory = f"{settings['output']}/{os.path.basename(benchmark['target'])}/{benchmark['block_size']}"
    return directory


def check_target_type(target, filetype):
    """ Validate path and file / directory type.
    It also returns the appropritate fio command line parameter based on the
    file type. 
    """

    keys = ['file', 'device', 'directory']

    test = {
        keys[0]: Path.is_file,
        keys[1]: Path.is_block_device,
        keys[2]: Path.is_dir
    }

    parameter = {
        keys[0]: '--filename',
        keys[1]: '--filename',
        keys[2]: '--directory'
    }

    if not os.path.exists(target):
        print(f"Benchmark target {filetype} {target} does not exist.")
        sys.exit(10)

    if filetype not in keys:
        print(f"Error, filetype {filetype} is an unknown option.")
        exit(123)

    check = test[filetype]

    path_target = Path(target)  # path library needs to operate on path object

    if check(path_target):
        return parameter[filetype]
    else:
        print(f"Target {filetype} {target} is not {filetype}.")
        sys.exit(10)


def run_fio(settings, benchmark):
    output_directory = generate_output_directory(settings, benchmark)
    make_directory(output_directory)
    output_file = f"{output_directory}/{benchmark['mode']}-{benchmark['iodepth']}-{benchmark['numjobs']}.json"

    command = ["fio", f"--output-format=json",
               f"--output={output_file}", settings['template']]

    target = benchmark['target']

    if settings['size']:
        command.append(f"--size={settings['size']}")

    target_parameter = check_target_type(target, settings['type'])

    command.append(f"{target_parameter}={target}")

    if settings['rwmixread'] and benchmark['mode'] in settings['mixed']:
        command.append(f"--rwmixread={benchmark['rwmixread']}")

    if settings['extra_opts']:
        for option in settings['extra_opts']:
            option = str(option)
            command.append(f"--"+option)
    run_command(settings, benchmark, command)


def run_benchmarks(settings, benchmarks):
    if not settings['quiet']:
        for benchmark in ProgressBar(benchmarks):
            run_fio(settings, benchmark)
    else:
        for benchmark in benchmarks:
            run_fio(settings, benchmark)


def ProgressBar(iterObj):
    """ https://stackoverflow.com/questions/3160699/python-progress-bar/49234284#49234284
    """
    def SecToStr(sec):
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        return u'%d:%02d:%02d' % (h, m, s)
    L = len(iterObj)
    steps = {int(x): y for x, y in zip(linspace(0, L, min(100, L), endpoint=False),
                                       linspace(0, 100, min(100, L), endpoint=False))}
    # quarter and half block chars
    qSteps = ['', u'\u258E', u'\u258C', u'\u258A']
    startT = time.time()
    timeStr = '   [0:00:00, -:--:--]'
    activity = [' -', ' \\', ' |', ' /']
    for nn, item in enumerate(iterObj):
        if nn in steps:
            done = u'\u2588'*int(steps[nn]/4.0)+qSteps[int(steps[nn] % 4)]
            todo = ' '*(25-len(done))
            barStr = u'%4d%% |%s%s|' % (steps[nn], done, todo)
        if nn > 0:
            endT = time.time()
            timeStr = ' [%s, %s]' % (SecToStr(endT-startT),
                                     SecToStr((endT-startT)*(L/float(nn)-1)))
        sys.stdout.write('\r'+barStr+activity[nn % 4]+timeStr)
        sys.stdout.flush()
        yield item
    barStr = u'%4d%% |%s|' % (100, u'\u2588'*25)
    timeStr = '   [%s, 0:00:00]\n' % (SecToStr(time.time()-startT))
    sys.stdout.write('\r'+barStr+timeStr)
    sys.stdout.flush()


def generate_test_list(settings):
    """ All options that need to be tested are multiplied together.
    This creates a full list of all possible benchmark permutations that
    need to be run.
    """
    loop_items = settings['loop_items']

    dataset = []
    for item in loop_items:
        result = settings[item]
        dataset.append(result)

    benchmark_list = itertools.product(*dataset)
    #pprint.pprint([x for x in benchmark_list])
    return [dict(zip(loop_items, item)) for item in benchmark_list]


def get_arguments(settings):
    parser = argparse.ArgumentParser(
        description="Automates FIO benchmarking. It can run benchmarks \
            with different iodepths, jobs or other properties.")
    ag = parser.add_argument_group(title="Generic Settings")
    ag.add_argument("-d", "--target",
                    help="Storage device / directory / file to be tested", required=True, nargs='+', type=str)
    ag.add_argument("-t", "--type", help="Target type, device, file or directory",
                    choices=['device', 'file', 'directory'], required=True)
    ag.add_argument(
        "-s", "--size", help="File size if target is a file. If target \
            is a directory, a file of the specified size is created per job", type=str)
    ag.add_argument("-o", "--output",
                    help=f"Output directory for .json and .log output. If a read/write mix is specified,\
                    separate directories for each mix will be created.", required=True)
    ag.add_argument(
        "-j", "--template", help=f"Fio job file in INI format. A file is already included and this parameter is only required if you create your own custom Fio job. \
            (Default: {settings['template']})", default=settings['template'])
    ag.add_argument("-b", "--block-size",
                    help=f"Specify block size(s). (Default: {settings['block_size']}", default=settings['block_size'], nargs='+')
    ag.add_argument(
        "--iodepth", help=f"Override default iodepth test series\
             ({settings['iodepth']}). Usage example: --iodepth 1 8 16", nargs='+', type=int,
        default=settings['iodepth'])
    ag.add_argument(
        "--numjobs", help=f"Override default number of jobs test series\
            ({settings['numjobs']}). Usage example: --numjobs 1 8 16", nargs='+', type=int, default=settings['numjobs'])
    ag.add_argument(
        "--duration", help=f"Override the default test duration per benchmark \
            (default: {settings['duration']})", type=int, default=settings['duration'])
    ag.add_argument(
        "-m", "--mode", help=f"List of I/O load tests to run (default: \
            {settings['mode']})", default=settings['mode'], nargs='+', type=str)
    ag.add_argument("--rwmixread", help=f"If a mix of read/writes is specified \
        with --testmode, the ratio of reads vs. writes can be specified with this option.\
            the parameter is an integer and represents the percentage of reads.\
             A read/write mix of 75%%/25%%  is specified as '75' (default: {settings['rwmixread']}).\
                Multiple values can be specified and separate output directories will be created.\
                    This argument is only used if the benchmark is of type randrw. Otherwise \
                        this option is ignored.", nargs='+', type=int, default=settings['rwmixread'])
    ag.add_argument(
        "-e", "--engine", help=f"Select the ioengine to use, see fio --enghelp \
            for an overview of supported engines. (Default: {settings['engine']}).", default=settings['engine'])
    ag.add_argument(
        "--direct", help=f"Use DIRECT I/O \
            (default: {settings['direct']})", type=int, default=settings['direct'])
    ag.add_argument("--extra-opts", help=f"Allows you to add extra options, \
        for example, options that are specific to the selected ioengine. It \
             can be any other Fio option. Example: --extra-opts norandommap=1 invalidate=0\
                 You may also choose to add those options to the fio_template.fio file.", nargs='+')
    ag.add_argument("--invalidate", type=int,
                    help=f"From the Fio manual: Invalidate buffer-cache for the \
                        file prior to starting I/O.(Default: {settings['invalidate']})", default=settings['invalidate'])
    ag.add_argument(
        "--quiet", help="The progresbar will be supressed.", action='store_true')
    ag.add_argument(
        "--loginterval", help=f"Interval that specifies how often stats are \
            logged to the .log files. (Default: {settings['loginterval']}", type=int, default=settings['loginterval'])
    ag.add_argument(
        '--dry-run', help="Simulates a benchmark, does everything except running\
             Fio.", action='store_true', default=False)
    return parser


def get_argument_description():
    descriptions = {
        'target': 'Test target',
        'template': 'Job template',
        'engine': 'I/O Engine',
        'mode': 'Test mode (read/write)',
        'iodepth': 'IOdepth to be tested',
        'numjobs': 'NumJobs to be tested',
        'block_size': 'Block size',
        'direct': 'Direct I/O',
        'size': 'Specified test data size',
        'rwmixread': 'Read/write mix in %% read',
        'duration': 'Time duration per test (s)',
        'extra_opts': 'Extra custom options',
        'loginterval': 'Log interval of perf data',
        'invalidate': 'Invalidate buffer cache',
        'type': 'Target type',
        'output': 'Output folder',
    }
    return descriptions


def get_default_settings():

    settings = {}
    settings['target'] = []
    settings['template'] = "./fio-job-template.fio"
    settings['engine'] = "libaio"
    settings['mode'] = ["randread", "randwrite"]
    settings['iodepth'] = [1, 2, 4, 8, 16, 32, 64]
    settings['numjobs'] = [1, 2, 4, 8, 16, 32, 64]
    settings['block_size'] = ["4k"]
    settings['direct'] = 1
    settings['size'] = None
    settings['rwmixread'] = None
    settings['duration'] = 60
    settings['extra_opts'] = []
    settings['loginterval'] = 500
    settings['mixed'] = ['readwrite', 'rw', 'randrw']
    settings['invalidate'] = 1
    settings['loop_items'] = ['target', 'mode', 'iodepth',
                              'numjobs', 'block_size']
    settings['filter_items'] = ['filter_items',
                                'loop_items', 'dry_run', 'mixed', 'quiet']
    return settings


def calculate_duration(settings, tests):
    number_of_tests = len(tests)
    time_per_test = settings['duration']
    duration_in_seconds = number_of_tests * time_per_test
    duration = str(datetime.timedelta(seconds=duration_in_seconds))
    return duration


def parse_settings_for_display(settings):
    data = {}
    max_length = 0
    action = {
        list: lambda a: ' '.join(map(str, a)),
        str: str,
        int: str,
        bool: str
    }
    for k, v in settings.items():
        if v:
            data[str(k)] = action[type(v)](v)
            length = len(data[k])
            if length > max_length:
                max_length = length
    data['length'] = max_length
    return data


def check_if_mixed_workload(settings):
    options = settings['mixed']
    for mode in settings['mode']:
        if mode in options:
            return True
        else:
            return False


def display_header(settings, tests):
    header = f"+++ Fio Benchmark Script +++"
    blockchar = u'\u2588'
    data = parse_settings_for_display(settings)
    fl = 30  # Width of left column of text
    length = data['length']
    width = length + fl - len(header)
    duration = calculate_duration(settings, tests)
    print(f"{blockchar}" * (fl + width))
    print((" " * int(width/2)) + header)
    print()
    if settings['dry_run']:
        print()
        print(f" ====---> WARNING - DRY RUN <---==== ")
        print()
    estimated = "Estimated duration"
    print(f"{estimated:<{fl}}: {duration:<}")
    descriptions = get_argument_description()
    for item in settings.keys():
        if item not in settings['filter_items']:
            description = descriptions[item]
            if item in data.keys():
                print(f"{description:<{fl}}: {data[item]:<}")
            else:
                if settings[item]:
                    print(f"{description}:<{fl}: {settings[item]:<}")
    print()
    print(f"{blockchar}" * (fl + width))


def check_args(settings):
    """ Some basic error handling.
    """
    try:
        parser = get_arguments(settings)
        args = parser.parse_args()

    except OSError:
        parser.print_help()
        sys.exit(1)

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(2)

    if not check_fio_version(settings):
        parser.print_help()
        sys.exit(3)

    return args


def check_settings(settings):
    """ Some basic error handling.
    """
    if not os.path.exists(settings['template']):
        print()
        print(f"The specified template {settings['template']} does not exist.")
        print()
        sys.exit(6)

    if settings['type'] != 'device' and not settings['size']:
        print()
        print("When the target is a file or directory, --size must be specified.")
        print()
        sys.exit(4)

    if settings['type'] == 'directory':
        for item in settings['target']:
            if not os.path.exists(item):
                print(
                    f"\nThe target directory ({item}) doesn't seem to exist.\n")
                sys.exit(5)

    for mode in settings['mode']:
        if mode in settings['mixed']:
            if settings['rwmixread']:
                settings['loop_items'].append('rwmixread')
            else:
                print(
                    f"\nIf a mixed (read/write) mode is specified, please specify --rwmixread\n")
                sys.exit(6)
        else:
            settings['filter_items'].append('rwmixread')


def check_encoding():
    try:
        print(u"\u3000")  # blank space
    except UnicodeEncodeError:
        print()
        print(
            f"It seems your default encoding is not UTF-8. This script requires UTF-8.")
        print(f"You can change the default encoding with 'export PYTHONIOENCODING=UTF-8'")
        print(f"Or you can run the script like: PYTHONIOENCODING=utf-8 ./bench_fio")
        print(f"Changing the default encoding could affect other applications, beware.")
        print()
        exit(90)


def check_if_fio_exists():
    command = 'fio'
    if(shutil.which(command) is None):
        print("Fio executable not found in path. Is Fio installed?")
        print()
        sys.exit(1)


def main():
    check_encoding()
    check_if_fio_exists()
    settings = get_default_settings()
    args = check_args(settings)
    customsettings = vars(args)
    settings = {**settings, **customsettings}
    check_settings(settings)
    tests = generate_test_list(settings)
    display_header(settings, tests)
    if not settings['dry_run']:
        run_benchmarks(settings, tests)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\nControl-C pressed - quitting...")
        sys.exit(1)

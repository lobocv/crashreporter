CrashReporter
=============

CrashReporter creates reports from the traceback if your python code crashes. The reports can be uploaded directly
to the developers via email or FTP. If no internet connection is available, crash reporter stores offline reports and
later sends them when possible.


Features
--------
Features of crashreporter include:

    - Uploading of crash reports via email or FTP.
    - Offline crash reporting that stores crash reports until they are uploaded.
    - Traceback and local variable output


Installation
------------
To install:
    
    pip install crashreporter
    
    
Usage
-----
    
Implementing the crash reporter is easy. Just create a CrashReporter object. Configure the SMTP or FTP accounts for 
uploading of reports (optional) and then wrap your code in the context manager of the crash reporter.

In the following example, we wil create a Person class that has an optional age  attribute. We will then create two
Person objects, one with an age and one without. When we attempt to combine their ages we get the following error:

    TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'


example.py

```python

    from crashreporter import CrashReporter
    
    class Person(object):
    
        def __init__(self, name, age=None):
            self.name = name
            self.age = age
    
    def combine_ages(person_a, person_b):
        a_local_variable = 134
        return person_a.age + person_b.age
    
    if __name__ == '__main__':
        cr = CrashReporter(report_dir='/home/calvin/crashreporter',
                           check_interval=3600,
                            html=True)
        cr.application_name = 'My App'
        cr.application_version = '1.1.350'
                                    
        # Configure the crash reporter to email myaddress@gmail.com 
        # whenever a crash is detected
        cr.setup_smtp(user="crashreporter@gmail.com",
                      passwd='12345678',
                      recipients=['myaddress@gmail.com'],
                      host="smtp.gmail.com",
                      port=587)
                      
        # Configure the crash reporter to upload crash reports 
        # to ftp.example.com whenever a crash is detected
        cr.setup_ftp(host='ftp.example.com',
                     user='user',
                     passwd='12345',
                     path='./myapp/crashreports')
    
        with cr:
            calvin = Person('calvin', age=25)
            bob = Person('bob')
            combine_ages(calvin, bob)


```
    
When the crash occurs, the crash reporter will attempt to send it by email or upload it to the FTP server, if both methods
fail, the crash is written to file in `report_dir`. The next time the script is run, the crash reporter will look for
any offline reports and attempt to send them every `check_interval` seconds. After a sucessful upload, the stored reports
are deleted.

To get crash reports for you entire script, you can wrap your script in a main() function and have the crash reporter
envelope it, like so:

```python

    from myscript import main
    
    with cr:
        main()
    
        
```

Configuration File
------------------
If you don't want to keep your SMTP and FTP credentials in your scripts you can alternatively use a configuration file.
Simple pass the path to the configuration file as the `config` argument in CrashReporter or call the `load_configuration(path)`
method with the path. The format of the configuration file should have two sections, SMTP and FTP. Under each section are parameters
that are passed to the setup_smtp and setup_ftp functions:

Example:

    [SMTP]
    user = mycrashreporter@gmail.com
    passwd = mypasswordissupersecret
    recipients = developer1@gmail.com, developer2@gmail.com
    host = smtp.gmail.com
    port = 587
    
    [FTP]
    user = user
    passwd = 12345
    host = ftp.example.com
    path = ./myapp/crashreports
    port = 2456
    


Attributes
----------

The CrashReporter has several attributes that can be changed:
 
    offline_report_limit:   
            The maximum number of offline reports to save before overwriting 
            the oldest report.
            
    application_version:    
            Application version as a string to be included in the report.
            
    application_name:       
            Application name as a string to be included in the report.
            
    source_code_line_limit: 
            The number of source code lines to include before and after the error 
            as a tuple (before, after) 


    
    

Example Report
--------------


![alt tag](https://raw.github.com/lobocv/crashreporter/readme/example.png)
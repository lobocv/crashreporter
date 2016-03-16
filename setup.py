__author__ = 'lobocv'
__version__ = '1.11'

from distutils.core import setup

setup(
    name='crashreporter',
    packages=['crashreporter'],  # this must be the same as the name above
    package_dir={'crashreporter': 'crashreporter'},
    package_data={'crashreporter': ['*.html']},
    version=__version__,
    description='Track and send crash reports by email or FTP',
    author='Calvin Lobo',
    author_email='calvinvlobo@gmail.com',
    license='MIT',
    url='https://github.com/lobocv/crashreporter',
    download_url='https://github.com/lobocv/crashreporter/tarball/%s' % __version__,
    keywords=['crash', 'reporting', 'testing', 'debugging', 'bugs'],
    classifiers=[],
    install_requires=["Jinja2==2.8",
                      "requests==2.8.1"]
)

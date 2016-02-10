import setuptools
import subprocess

with open('README.md') as f:
    readme = f.read()

major_version = '1.0'
commits = subprocess.check_output(
    ['/usr/bin/git', 'rev-list', 'HEAD', '--count']).decode('utf8').strip()

setuptools.setup(
    name='pyscp',
    version='{}.{}'.format(major_version, commits),
    description='Python API and utilities for the scp-wiki.net website.',
    long_description=readme,
    url='https://github.com/anqxyr/pyscp/',
    author='anqxyr',
    author_email='anqxyr@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Other Audience',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.4'],
    packages=['pyscp'],
    install_requires=[
        'arrow',
        'beautifulsoup4',
        'blessings',
        'lxml',
        'requests',
        'peewee'],
)

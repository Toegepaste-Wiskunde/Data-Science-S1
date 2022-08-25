
import sys
import nbformat
from pathlib import PosixPath, Path
from nbconvert.preprocessors import ExecutePreprocessor
from IPython.core.error import StdinNotImplementedError
import os
import shutil
import glob
import sqlite3
import uuid
import pandas as pd
import time
from IPython.core.display import HTML
from collections import defaultdict
import getpass

PATH_TIMEOUT = 600
KERNEL = 'prog'

class _notebook:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def from_notebook(cls, path: Path, notebook):
        r = cls(path / notebook.folder / notebook.file)
        r._notebook = notebook.notebook
        return r   

    @property
    def notebook(self):
        try:
            return self._notebook
        except:
            with open(self.path) as fin:
                self._notebook = nbformat.read(fin, as_version=4)
            return self._notebook
    
    def is_valid(self):
        folder = self.path.parts[-2]
        return not folder.startswith('.')

    def __repr__(self):
        return str(self.path)
    
    @property
    def key(self):
        return (self.folder, self.assignment)
    
    @property
    def folder(self):
        return self.path.parts[-2]
    
    @property
    def file(self):
        return self.path.parts[-1]
    
    @property
    def assignment(self):
        return self.file.rsplit('.', 1)[0]
    
    def exists(self):
        return self.path.exists()
    
    @property
    def mtime(self):
        return os.path.getmtime(self.path)
    
    def _modify_cell(self, c):
        c.points = 0
        #print(c.outputs)
        try:
            c.points = '<tr style="background: green; color: white">' in c.outputs[0].data['text/html']
        except: pass
        c.source = c.source.strip()
        c.assignment = c.source.startswith('%%assignment')
        c.check = c.source.startswith('%%check')
        return c
    
    def check_cells(self):
        r = [ self._modify_cell(c) for c in self.notebook.cells if c.cell_type == 'code' ]
        i = 0
        last_assignment = ''
        while i < len(r):
            if i < len(r) and r[i].assignment and r[i+1].assignment:
                del r[i]
            elif r[i].assignment:
                last_assignment = r[i].source
                del r[i]
            elif r[i].check:
                r[i].assignment_source = last_assignment
                i += 1
            else:
                del r[i]
        return r
    
    def is_newer(self, other):
        return self.mtime > other.mtime
    
    def create_if_not_exists(self):
        self.path.parent.resolve().mkdir(exist_ok=True, parents=True)

    def write(self):
        self.create_if_not_exists()
        with open(self.path, 'w', encoding='utf-8') as fout:
            nbformat.write(self.notebook, fout)
    
    def generate_assignment(self, assignments):
        #p = assignments.notebook_path( self )
        n = _notebook.from_notebook(assignments, self)
        n.notebook.metadata['kernelspec'] = {'display_name': 'prog', 'language': 'python', 'name': 'prog'},
        for c in n.notebook.cells:
            if c.cell_type == 'code':
                if c.source.strip().startswith('%%check'):
                    c.metadata = {'trusted': True, 'editable': False, 'deletable': False}
                elif c.source.strip().startswith('%%assignment'):
                    c.metadata = {'trusted': True, 'editable': True, 'deletable': False}
                    p1 = c.source.find('\n### BEGIN SOLUTION')
                    p2 = c.source.find('\n### END SOLUTION')
                    if p1 > -1 and p2 > p1:
                        c.source = c.source[:p1] + '\n### ENTER YOUR CODE HERE' + c.source[p2+17:]  
        return n

    def copy_user(self, userfolder ):
        n = usernotebook( userfolder.notebook_path( notebook ) )
        n._notebook = self.notebook
        return 

class notebooks(PosixPath):
    """
    A (nested) folder containing notebooks
    """
    def __new__(cls, *path, **kwargs):
        return PosixPath.__new__(cls, *path)
        
    def __init__(self, path, clazz=None, user=None, subpath='*/*.ipynb'):
        super().__init__()
        clazz = clazz or notebook
        self.notebooks_dict = dict()
        self.path = path
        self.user = user
        for f in self.glob(subpath):
            n = clazz(f)
            if n.is_valid():
                self[n.key] = n
    
    def notebook_path(self, notebook):
        try:
            if self.user:
                return Path(str(self.path).replace('*', self.user)) / notebook.folder / notebook.file
        except: pass
        return Path(self.path) / notebook.folder / notebook.file
    
    def find_usernotebook(self, notebook):
        return usernotebook( self.notebook_path(notebook) )

    def add(self, notebook):
        self[notebook.key] = notebook
        
    def __getitem__(self, notebook):
        try:
            return self.notebooks_dict[notebook.key]
        except: pass
    
    def __setitem__(self, key, notebook):
        self.notebooks_dict[key] = notebook
    
    @property
    def notebooks(self):
        return self.notebooks_dict.values()
    
    def __iter__(self):
        return iter(self.notebooks)
    
    def list(self):
        return list(self)

class usernotebooks(dict):
    def __init__(self, path='/home/*/notebooks/ds1', clazz=None, subpath='*/*.ipynb'):
        self.users = dict()
        self.path = path
        self.clazz = clazz or usernotebook
        for p in glob.glob(path):
            user = self.user_from_path(p)
            self[user] = notebooks(Path(p), clazz=self.clazz, user=user, subpath=subpath)

    def user_from_path(self, pathstr):
        return pathstr.split('/')[1]
            
    def notebook_path(self, notebook):
        return Path(self.path.replace('*', notebook.user)) / notebook.folder / notebook.file 

    def find_usernotebook(self, n):
        return self[n.user].find_usernotebook(n)
    
    def add(self, notebook):
        self[notebook.user].add(notebook)
            
    def __setitem__(self, key, value):
        self.users[key] = value
        
    def __getitem__(self, key):
        try:
            return self.users[key]
        except:
            self.users[key] = notebooks(self.path.replace('*', key), clazz=self.clazz, user=key)
            return self.users[key]
    
    def __iter__(self):
        return iter(self.users.values())

    def list(self):
        return list(self)

class notebook(_notebook):
    def __hash__(self):
        return hash(self.key)
    
    def __eq__(self, other: _notebook) -> bool:
        return self.folder == other.folder and self.assignment == other.assignment    

    def _db_add_checks(self, db):
        for c in self.check_cells():
            db.add_check( self.folder, self.assignment, c.source)
            
class usernotebook(_notebook):
    @property
    def user(self):
        if self.path.parts[1] == 'home':
            return self.path.parts[2]
        else:
            return self.path.parts[4]
                        
    def username(self):
        return list(self._usernames)[0]

class ds1:    
    @property
    def assignments(self):
        try:
            return self._assignments
        except:
            self._assignments = notebooks('/data/ds1/assignments')
            return self._assignments

    @property
    def user(self):
        try:
            return self._user
        except:
            self._user = usernotebooks('/home/*/notebooks/ds1')
            return self._user

    def copy_assignments(self, user):
        for n in self.assignments:
            self.nb = n
            self.nb = self.user[user].find_usernotebook( n)
            if not self.nb.exists():
                self.nb._notebook = n.notebook
                self.nb.write()

if __name__ == '__main__':
    ds = ds1()
    user = getpass.getuser()
    ds.copy_assignments(user)


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
    @classmethod
    def from_notebook(cls, path: Path, notebook):
        r = cls(path / notebook.folder / notebook.file)
        r._notebook = notebook.notebook
        return r
        
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

    @property
    def userfraude(self):
        try:
            return self._userfraude
        except:
            self._userfraude = False
            for c in self.notebook.cells:
                try:
                    user = c.outputs[0].metadata['text/html'].username
                    if user[0] >= '0' and user[0] <= '9' and user != self.user:
                        self._userfraude = True
                        break
                except: pass
            return self._userfraude
                        
    def username(self):
        return list(self._usernames)[0]
    
    def submit(self):
        n = submittednotebook(self.path)
        os.environ['progusername'] = n.user
        ep = ExecutePreprocessor(timeout=PATH_TIMEOUT, kernel_name=KERNEL)
        ep.allow_errors = True
        try:
            ep.preprocess(n.notebook, {'metadata': {'path': str(self.path.parent.resolve())}})
            n.error = False
        except:
            raise
            n.error = True
        return n
    
    def to_db(self, db):
        db.query(f"""delete from submit where user='{self.user}' and folder='{self.folder}' 
                        and assignment='{self.assignment}'""")
        for c in self.check_cells():
            db.add_submit(self.user, self.folder, self.assignment, c.source, c.assignment_source, c.points, 
                          self.mtime, self.error)
            if self.userfraude:
                db.add_userfraude(self.user, self.folder, self.assignment, c.source, c.assignment_source, c.points, 
                              self.mtime, self.error)

class submittednotebook(usernotebook):
    def __init__(self, path):
        super().__init__(path)
        self.writable = True
    
    def write(self):
        assert str(self.path).startswith('/data'), 'Trying to write a submitted notebook in a user folder'
        super().write()
    
    def remove_file_and_empty_folder(self):
        self.path.unlink()
        folder = self.path.parent.resolve()
        if len(list(folder.glob('*'))) == 0:
            folder.unlink()
        
    def grade(self, db, valid_check):
        for c in self.check_cells():
            if valid_check(self, c):
                pass

class userfraudenotebook(usernotebook):
    @property
    def folder(self):
        return self.path.parts[-3]
    
    @property
    def file(self):
        return self.path.parts[-1]
    
    @property
    def assignment(self):
        return self.path.parts[-2]

class submittednotebooks(usernotebooks):
    def __init__(self, path, clazz=submittednotebook, subpath='*/*.ipynb'):
        super().__init__(path, clazz=clazz, subpath=subpath)

    def user_from_path(self, pathstr):
        return pathstr.split('/')[3]

    def _clear(self):
        for p in glob.glob(self.path):
            shutil.rmtree(p)
            
class userfraudenotebooks(submittednotebooks):
    def __init__(self, path):
        super().__init__(path=path, clazz=userfraudenotebook, subpath='*/*/*.ipynb')

    def notebook_path(self, notebook):
        file = str(uuid.uuid4()) + '.ipynb'
        return Path(self.path.replace('*', notebook.user)) / notebook.folder / notebook.assignment /  file

class db:
    def __init__(self, dbfile = '/data/ds1/answers/prog.db'):
        if not Path(dbfile).exists():
            self.db = sqlite3.connect(dbfile)
            self.create_tables()
        else:
            self.db = sqlite3.connect(dbfile)
    
    def escape(self, text):
        return text.replace("'", "''")
    
    def _query(self, q):
        try:
            c = self.db.cursor()
            c.execute(q)
            return c
        except sqlite3.Error as e:
            print(e)
    
    def query(self, q):
        self._query(q)
        self.db.commit()
    
    def select(self, q):
        c = self._query(q)
        r = c.fetchall()
        self.db.commit()
        return r
    
    def create_tables(self):
        self.query("""CREATE TABLE IF NOT EXISTS submit (
                                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        user TEXT NOT NULL,
                                        folder TEXT NOT NULL,
                                        assignment TEXT NOT NULL,
                                        question TEXT,
                                        answer TEXT,
                                        points INTEGER,
                                        time REAL,
                                        error INTEGER
                                    ); """)
        self.query("""CREATE TABLE IF NOT EXISTS userfraude (
                                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        user TEXT NOT NULL,
                                        folder TEXT NOT NULL,
                                        assignment TEXT NOT NULL,
                                        question TEXT,
                                        answer TEXT,
                                        points INTEGER,
                                        time REAL,
                                        error INTEGER
                                    ); """)

        
    def db_create_checks_table(self, assignments):
        self.query("""CREATE TABLE IF NOT EXISTS checks (
                                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        folder TEXT,
                                        assignment TEXT,
                                        code TEXT
                                    ); """)
        self.query("delete from checks")
        for n in assignments.notebooks:
            n._db_add_checks(self)                   

    def list_checks(self):
        return self.select('select * from checks')
            
    def add_check(self, folder, assignment, code):
        code = self.escape(code)
        self.query(f"""insert into checks (folder, assignment, code) 
                       values ('{folder}', '{assignment}', '{code}');""")
        
    def add_submit(self, user, folder, assignment, question, answer, points, time, error):
        question = self.escape(question)
        answer = self.escape(answer)
        self.query(f"""insert into submit (user, folder, assignment, question, answer, points, time, error) 
                       values ('{user}', '{folder}', '{assignment}', '{question}', '{answer}', {points}, {time}, {error});""")

    def add_userfraude(self, user, folder, assignment, question, answer, points, time, error):
        question = self.escape(question)
        answer = self.escape(answer)
        self.query(f"""insert into userfraude (user, folder, assignment, question, answer, points, time, error) 
                       values ('{user}', '{folder}', '{assignment}', '{question}', '{answer}', {points}, {time}, {error});""")

class ds1:    
    @property
    def assignments(self):
        try:
            return self._assignments
        except:
            self._assignments = notebooks('/data/ds1/assignments')
            return self._assignments

    @property
    def answers(self):
        try:
            return self._answers
        except:
            self._answers = notebooks('/data/ds1/answers')
            return self._answers

    @property
    def error(self):
        try:
            return self._error
        except:
            self._error = submittednotebooks('/data/ds1/error/*')
            return self._error


    @property
    def submit(self):
        try:
            return self._submit
        except:
            self._submit = submittednotebooks('/data/ds1/submit/*')
            return self._submit

    @property
    def userfraude(self):
        try:
            return self._userfraude
        except:
            self._userfraude = userfraudenotebooks('/data/ds1/userfraude/*')
            return self._userfraude

    @property
    def user(self):
        try:
            return self._user
        except:
            self._user = usernotebooks('/home/*/notebooks/ds1')
            return self._user

    @property
    def db(self):
        try:
            return self._db
        except:
            self._db = db()
            return self._db
    
    @property
    def _checks(self):
        try:
            return self.__checks
        except:
            self.__checks = { hash((n.assignment, c.source)) for n in self.assignments.notebooks for c in n.check_cells() }
            return self.__checks

    @property
    def report(self):
        try:
            return self._report
        except:
            self._report = report(self.db)
            return self._report
        
    def valid_check(self, notebook, cell):
        return hash((notebook.assignment, cell.source)) in self._checks
        
    def generate_assignments(self, force=False):
        if force:
            shutil.rmtree(self.assignments.path)

        for n in self.answers:
            self.nb = n
            n = n.generate_assignment(self.assignments)
            n.write()
        try:
            del self._assignments
        except: pass

    def copy_assignments(self, user):
        for n in self.assignments:
            self.nb = n
            self.nb = self.user[user].find_usernotebook( n)
            if not self.nb.exists():
                self.nb._notebook = n.notebook
                self.nb.write()
         
    def grab_submissions(self, force=False, timeout=280):
        t = time.time() + timeout
        if force:
            self.error._clear()
            self.submit._clear()
            self.userfraude._clear()
            
        for notebooks in self.user:
            for n in notebooks:
                print(n)
                self.nb = n
                if n.userfraude:
                    f = userfraudenotebook( self.userfraude.notebook_path( n ) )
                    f._notebook = n.notebook
                    f.path = self.userfraude.notebook_path( n )
                    f.write()
                    print('fraude', f.path)

                submit = self.submit[n.user].find_usernotebook( n )
                if submit.exists() and submit.is_newer( n ):
                    continue
                error = self.error[n.user].find_usernotebook( n )
                if error.exists() and error.is_newer( n ):
                    continue

                s = n.submit()
                if s.error:
                    s.path = self.error.notebook_path( n )
                else:
                    s.path = self.submit.notebook_path( n )
                s.write()
                self.nb = s
                s.to_db(self.db)
                if t > time.time():
                    break

    def create_checks_table(self):
        self.db.db_create_checks_table(d.assignments)
                

class report:
    def __init__(self, db):
        self.db = db
        
    @property
    def students(self):
        try:
            return self._students
        except:
            r = self.db.select('select user, sum(points) from submit group by user order by 1 desc')
            self._students = { c[0]:c[1] for c in r }
            return self._students
        
    @property
    def assignments(self):
        try:
            return self._assignments
        except:
            r = self.db.select('select folder, count(*) from checks group by folder order by 1')
            self._assignments = { self.convert_folder(c[0]):c[1] for c in r }
            return self._assignments

    @property
    def total(self):
        try:
            return self._total
        except:
            self._total = self.db.select('select count(*) from checks')[0][0]
            return self._total

    def convert_folder(self, x):
        return x.replace('_', ' ').split()[0]
       
    @property
    def scored(self):
        try:
            return self._scored
        except:
            r = defaultdict(lambda: 0)
            for row in self.db.select('select user, folder, sum(points) from submit group by user, folder'):
                r[(row[0], self.convert_folder(row[1]))] = row[2]
            self._scored = r
            return self._scored
        
    def submissions(self):
        df = pd.DataFrame(self.db.select('select * from submit'), 
                            columns=['id', 'user', 'folder', 'assignment', 'question', 'answer', 'points', 'time', 'error'])    
        df = self.convert_folder(df)
        return df
        
    def checks(self):
        df = pd.DataFrame(self.db.select('select * from checks'), 
                            columns=['id', 'folder', 'assignment', 'code'])
        df = self.convert_folder(df)
        return df.groupby( ['folder'] ).size().to_frame(name = 'count').reset_index()


    def fraud(self):
        df = pd.DataFrame(self.db.select('select * from userfraude'), 
                            columns=['id', 'user', 'folder', 'assignment', 'question', 'answer', 'points', 'time', 'error'])
        df = self.convert_folder(df)
        return df
    
    def style(self, assignment, score ):
        if self.assignments[assignment] == score:
            return ' bgcolor=lightgreen'
        return ''
    
    def summary(self):
        headers = ['Student']
        headers += self.assignments.keys()
        headers.append(f'Total')
        right = ' style="text-align:right"'
        
        r = '<table border=1><tr><th>'
        r += '</th><th>'.join(headers)
        r += '</th><tr>'
        
        r += f'<tr><td>Total</td><td{right}>' + f'</td><td{right}>'.join([ str(v) for v in self.assignments.values()])
        r += f'</td><td{right}>' + str(self.total) + '</td>'
        
        for s, total in self.students.items():
            scores = [ self.scored[(s, a)] for a in self.assignments ]
            styles = [ self.style(a, self.scored[(s, a)]) for a in self.assignments ]
            scores = scores + [ total ]
            r += f'</tr><tr><td>{s}'
            for sc, st in zip(scores, styles):
                r += f'</td><td{right}{st}>{sc}'
            r += f'</td><td{right}>{self.students[s]}</td>'
        
        r += '</tr></table>'
        return r

if __name__ == '__main__':
    assert len(sys.argv) > 1, '''
    Use check with:
        --fetch: fetch and grade user notebooks
        --summary: output an html summary
        --generate: generate assignments from /data/ds1/answers
        --generateforce: remove old assignments and generate new ones
    '''
    d = ds1()
    if sys.argv[1] == '--fetch':
        d.grab_submissions()
    elif sys.argv[1] == '--summary':
        print(d.report.summary())
    elif sys.argv[1] == '--generate':
        d.generate_assignments()
    elif sys.argv[1] == '--generateforce':
        d.generate_assignments(force=True)
    else:
        print('ik snap je niet')

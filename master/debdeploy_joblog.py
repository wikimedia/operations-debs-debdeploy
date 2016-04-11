# -*- coding: utf-8 -*-

import sqlite3, os

class DebDeployJobLog(object):
    '''
    This class manages software deployment jobs. The jobs are executed asynchronously
    by Salt and a Sqlite3 database is used to store which jobs have been issued/rolled
    back.
    '''

    sqlite_dbfilename = ''

    def __init__(self, dbfilename):
        self.sqlite_dbfilename = dbfilename

        if not os.path.exists(self.sqlite_dbfilename):
            conn = sqlite3.connect(self.sqlite_dbfilename)

            with conn:
                conn.execute('CREATE TABLE updates (updatespec text, servergroup text, jobid text, rollbackid text)')

    def add_job(self, yamlfile, servergroup, jid):
        '''
        This function records a software deployment in the job database.

        yamlfile = name of transaction file (string)
        servergroup = group of servers (specified in debdeploy.conf) (string)
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)

        v = (str(yamlfile), str(servergroup), str(jid), "")
        with conn:
            conn.execute('INSERT INTO updates VALUES (?, ?, ?, ?)', v)

    def does_job_exist(self, yamlfile, servergroup):
        '''
        This boolean function returns whether a software update has been deployed yet.

        yamlfile = name of transaction file (string)
        servergroup = group of servers (specified in debdeploy.conf) (string)
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)
        with conn:
            r = conn.execute("SELECT * FROM updates WHERE updatespec=? AND servergroup=?", (yamlfile,servergroup,)).fetchall()
            if len(r) > 0:
                return True
            else:
                return False

    def has_been_rolled_back(self, yamlfile, servergroup):
        '''
        This boolean function returns whether a deployed software update has been rolled back.

        yamlfile = name of transaction file (string)
        servergroup = group of servers (specified in debdeploy.conf) (string)
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)
        with conn:
            r = conn.execute("SELECT * FROM updates WHERE updatespec=? and servergroup=? and rollbackid !=''", (yamlfile,servergroup,)).fetchall()
            if len(r) > 0:
                return True
            else:
                return False


    def get_jobs(self, jobrange=0):
        '''
        This function returns a list all jobs.

        jobrange = returns only the last x commands (can be specified as a positive or negative number). If 0 is
                   passed or if left out, all jobs are returned
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)

        if jobrange == 0:
            with conn:
                r = conn.execute("SELECT * FROM updates").fetchall()

                if not r:
                    return None

                return r
        else:
            with conn:
                r = conn.execute("SELECT * FROM updates order by jobid desc limit ?", (abs(jobrange),)).fetchall()
                if not r:
                    return None

                return r

    def get_jobid(self, yamlfile, servergroup):
        '''
        This function returns the ID of a deployed software update. Returns None for
        invalid updatefile/server group.

        yamlfile = name of transaction file (string)
        servergroup = group of servers (specified in debdeploy.conf) (string)
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)

        with conn:
            r = conn.execute("SELECT jobid FROM updates WHERE updatespec=? and servergroup=?", (yamlfile,servergroup,)).fetchall()

            if not r:
                return None

            if len(r) > 1:
                raise ValueError, "Multiple jobs found for update " + yamlfile + " on server group " + servergroup
            else:
                return r[0][0]

    def get_rollbackid(self, yamlfile, servergroup):
        '''
        This function returns the ID of a rollback transaction. Returns None for
        invalid update/server group and an empty string for updates which haven't been
        rolled back yet.

        yamlfile = name of transaction file (string)
        servergroup = group of servers (specified in debdeploy.conf) (string)
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)

        with conn:
            r = conn.execute("SELECT rollbackid FROM updates WHERE updatespec=? and servergroup=?", (yamlfile,servergroup,)).fetchall()
            if not r:
                return None
            else:
                return r[0][0]

    def mark_as_rolled_back(self, jid, rid):
        '''
        This function records that a rollback has been issued via Salt.

        jid = The Salt job ID of the originally deployed update
        rid = The Salt job ID of the rollback
        '''
        conn = sqlite3.connect(self.sqlite_dbfilename)

        with conn:
            if not conn.execute("SELECT * FROM updates WHERE jobid=?", (jid,)).fetchall():
                raise ValueError, "Invalid job ID, doesn't exist in database"
            conn.execute("UPDATE updates SET rollbackid=? WHERE jobid=?", (rid, jid,))

# Local variables:
# mode: python
# End:

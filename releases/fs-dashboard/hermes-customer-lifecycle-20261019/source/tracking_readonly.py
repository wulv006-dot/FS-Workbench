"""Stored tracking reads through the original admin service, without observing or dispatching."""
from contextlib import closing, contextmanager
from copy import copy
from pathlib import Path
import sqlite3


@contextmanager
def _database(path):
    path=Path(path).absolute()
    if not path.is_file() or any(part.is_symlink() for part in (path,*path.parents)):
        raise OSError('tracking_read_store_unavailable')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        yield db


def stored_get(controller,user,params):
    controller.admin._admin(user)
    required={'mode':['hermes'],'structure':['customer_tracking'],'stored_only':['1']}
    if (not isinstance(params,dict) or any(params.get(key)!=value for key,value in required.items())
            or any(not isinstance(value,list) or len(value)!=1 or not isinstance(value[0],str) for value in params.values())):
        raise ValueError('tracking_read_query')
    view=params.get('view',[''])[0]
    field='day' if view=='candidates' else 'id' if view=='detail' else None
    if field is None or set(params)!=set(required)|{'view',field}:
        raise ValueError('tracking_read_query')
    # Keep the original Store/AdminService calculations and permissions; only the connection is read-only.
    store=copy(controller.store)
    store.db=lambda:_database(store.path)
    admin=copy(controller.admin)
    admin.store=store
    value=admin.get(user,view,**{'date' if field=='day' else 'id':params[field][0]})
    if view=='candidates':
        value['day']=value.pop('date')
    value.update(stored_only=True,refreshed=False)
    controller.admin._admin(user)
    return 200,value

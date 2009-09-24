from zope.interface import implements

from twisted.web.resource import IResource
from twisted.cred.portal import IRealm

from thundercloud.auth.dbchecker import DBChecker, IDBChecker, UserNotFound

from ..restApi.site import siteRoot

class RootRealm(object):
    implements(IRealm)

    def requestAvatar(self, avatarId, mind, *interfaces):
        if IResource in interfaces:
            return IResource, siteRoot, lambda: None
        raise NotImplementedError()

    
class RootDBChecker(DBChecker):
    implements(IDBChecker)
    
    def getUserAndPassword(self, username):
        results = self.db.execute("SELECT username, password FROM users WHERE username = ?", (username,)).fetchone()
        if results is None:
            raise UserNotFound
        else:
            return (results["username"], results["password"])
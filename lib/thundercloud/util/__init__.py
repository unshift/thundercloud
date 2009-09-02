import simplejson as json
import jsonpickle
import sqlite3

class DataObject(object):
    _attributes = {}

    def __init__(self, json=None):
        for key in self._attributes.keys():
            setattr(self, key, self._attributes[key])
        if json is not None: self.slurp(json)

    # representation: dictionary object
    def __repr__(self):
        obj = {}
        for key in self._attributes.keys():
            try:
                obj.update({ key: getattr(self, key) })
            except AttributeError:
                pass
        return obj
    
    # string representation: stringified JSON
    def __str__(self):
        return json.dumps(self.toJson())
    
    # used for SQLite adaptation
    def __conform__(self, protocol):
        if protocol == sqlite3.PrepareProtocol:
            return self.__str__()

    # json representation
    def toJson(self):
        return jsonpickle.Pickler(unpicklable=True).flatten(self.__repr__())    
    
    # conveniently import JSON
    def slurp(self, json):
        if json is None: return
        for key in json.keys():
            setattr(self, key, json[key])


def mergeDict(lhs, rhs, merge=lambda l, r: l):
    if type(lhs) != type(rhs) != dict:
        raise AttributeError

    if lhs == {}:
        return dict(rhs)
    
    if rhs == {}:
        return dict(lhs)
    
    result = dict(lhs)
    for k, v in rhs.iteritems():
        if lhs.has_key(k):
            result[k] = merge(lhs[k], rhs[k])
        else:
            result[k] = v
    
    return result

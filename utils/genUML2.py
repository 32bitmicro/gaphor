#!/usr/bin/env python
# vim:sw=4:et
#
# Create a UML 2.0 datamodel from the Gaphor 0.2.0 model file.
#
# To do this we do the following:
# 1. read the model file with the gaphor parser
# 2. Create a object herarcy by ordering elements based on generalizations

from gaphor.parser import parse, element, canvas, canvasitem
import sys, string, operator

# The kind of attribute we're dealing with:
ATTRIBUTE = 0
ENUMERATION = 1

header = """# This file is generated by genUML2.py. DO NOT EDIT!

from element import Element
from properties import association, attribute, enumeration, derivedunion, redefine
"""

# redefine 'bool' for Python version < 2.3
if map(int, sys.version[:3].split('.')) < [2, 3]:
    header = header + "bool = int\n"

class DevNull:
    def write(self, s):
        pass

def msg(s):
    sys.stderr.write(s)
    sys.stderr.write('\n')
    sys.stderr.flush()

def write_classdef(self, out):
    """Write a class definition (class xx(x): pass).
    First the parent classes are examined. After that its own definition
    is written. It is ensured that class definitions are only written
    once.
    
    For Diagram an exception is made: Diagram is imported from diagram.py"""
    if not self.written:
        s = ''
        for g in self.generalization:
            write_classdef(g, out)
            if s: s += ', '
            s = s + g['name']
        if not s: s = 'object'
        if self['name'] == 'Diagram':
            out.write('from diagram import Diagram\n')
        else:
            out.write('class %s(%s): pass\n' % (self['name'], s))
    self.written = True

def write_derivedunion(d, out):
    """Write a derived union to 'out'. If there are no subsets a warning
    is issued. The derivedunion is still created though."""
    subs = ''
    for u in d.union:
        if u.derived and not u.written:
            write_derivedunion(u, out)
        if subs: subs += ', '
        subs += '%s.%s' % (u.class_name, u.name)
    if subs:
        out.write("%s.%s = derivedunion('%s', %s, %s, %s)\n" %
                  (d.class_name, d.name, d.name, d.lower, d.upper, subs))
    else:
        msg('no subsets for derived union: %s.%s' % (d.class_name, d.name))
        out.write("%s.%s = derivedunion('%s', %s, %s)\n" %
                  (d.class_name, d.name, d.name, d.lower, d.upper))
    d.written = True

def write_redefine(r, out):
    out.write("%s.%s = redefine('%s', %s, %s)\n" %
              (r.class_name, r.name, r.name, r.opposite_class_name, r.redefines))

def parse_attribute(attr):
    """Returns a tuple (kind, derived, name, type, default, lower, upper)."""
    s = attr['name']
    kind = ATTRIBUTE
    derived = False
    default = None
    mult = None
    lower = 0
    upper = 1

    # First split name and type:
    name, type = map(string.strip, attr['name'].split(':'))
    while not name[0].isalpha():
        if name[0] == '/':
            derived = True
        name = name[1:]
    
    if '=' in type:
        # split the type part in type and default value:
        type, default = map(string.strip, type.split('='))
    elif '[' in type:
        # split the type part in type and multiplicity:
        type, mult = map(string.strip, type.split('['))

    if default and '[' in default:
        # check if the default part has a multiplicity defined:
        default, mult = map(string.strip, default.split('['))
        
    if mult:
        if mult[-1] == ']':
            mult = mult[:-1]
        m = map(string.strip, mult.split('.'))
        lower = m[0]
        upper = m[-1]
        if upper == '*':
            upper = "'*'"

    # Make sure types are represented the Python way:
    if default and default.lower() in ('true', 'false'):
        default = default.title() # True or False...

    if type.lower() == 'boolean':
        type = 'bool'
    elif type.lower() in ('integer', 'unlimitednatural'):
        type = 'int'
    elif type.lower() == 'string':
        type = '(str, unicode)'
    elif type.endswith('Kind'):
        kind = ENUMERATION

    return kind, derived, name, type, default, lower, upper

def parse_enumeration(enum):
    """Return a tuple of values."""
    values = ()
    print 'enum: ', enum['feature']
    for f in enum['feature']:
        print f['name']
        values = values + f['name']
    return values

def parse_association_name(name):
    # First remove spaces
    name = name.replace(' ','')
    derived = False
    while not name[0].isalpha():
        if name[0] == '/':
            derived = True
        name = name[1:]
    return derived, name

def parse_association_multiplicity(mult):
    subsets = []
    redefines = None
    tag = None
    if '{' in mult:
        # we have tagged values
        mult, tag = map(string.strip, mult.split('{'))
        if tag[-1] == '}':
            tag = tag[:-1]
    else:
        mult = mult.strip()
    
    mult = mult.split('.')
    lower = mult[0]
    upper = mult[-1]
    if lower == '*':
        lower = 0
    if upper == '*':
        upper = "'*'"

    if tag and tag.find('subsets') != -1:
        # find the text after 'subsets':
        subsets = tag[tag.find('subsets') + len('subsets'):]
        # remove all whitespaces and stuff
        subsets = subsets.replace(' ', '').replace('\n', '').replace('\r', '')
        subsets = subsets.split(',')
    if tag and tag.find('redefines') != -1:
        # find the text after 'redefines':
        redefines = tag[tag.find('redefines') + len('redefines'):]
        # remove all whitespaces and stuff
        redefines = redefines.replace(' ', '').replace('\n', '').replace('\r', '')
        l = redefines.split(',')
        assert len(l) == 1
        redefines = l[0]

    return lower, upper, subsets, redefines
        
def write_association(out, head, tail):
    """Write an association. False is returned if the association is derived.
    The head association end is enriched with the following attributes:
        derived - association is a derived union or not
        name - name of the association end (name of head is found on tail)
        class_name - name of the class this association belongs to
        opposite_class_name - name of the class at the other end of the assoc.
        lower - lower multiplicity
        upper - upper multiplicity
        subsets - derived unions that use the association
        redefines - redefines existing associations
    """
    navigable = tail.get('isNavigable')
    if navigable and not int(navigable):
        # from this side, the association is not navigable
        return True
    try:
        derived, name = parse_association_name(tail['name'])
    except KeyError:
        msg('ERROR! no name, but navigable: %s (%s.%s)' %
            (tail.id, tail.class_name, tail.name))
        return True

    lower, upper, subsets, redefines = parse_association_multiplicity(tail['multiplicity'])
    # Add the values found. These are used later to generate derived unions.
    head.derived = derived
    head.name = name
    head.class_name = head.participant['name']
    head.opposite_class_name = tail.participant['name']
    head.lower = lower
    head.upper = upper
    head.subsets = subsets
    head.redefines = redefines

    if derived or redefines:
        return False

    out.write("%s.%s = association('%s', %s, %s, %s" %
              (head.class_name, name, name, head.opposite_class_name, lower, upper))
    # Add the opposite property if the head itself is navigable:
    navigable = head.get('isNavigable')
    if not navigable or int(navigable):
        try:
            h_derived, h_name = parse_association_name(head['name'])
        except KeyError:
            msg('ERROR! no name, but navigable: %s (%s.%s)' %
                (head.id, head.class_name, head.name))
        else:
            assert not h_derived, 'One end if derived, the other end not ???'
            out.write(", '%s'" % h_name)
    out.write(')\n')
    return True

def generate(filename, outfile=None):
    # parse the file
    all_elements = parse(filename)

    if outfile:
        out = open(outfile, 'w')
    else:
        out = sys.stdout

    # extract usable elements from all_elements. Some elements are given
    # some extra attributes.
    classes = { }
    enumerations = { }
    generalizations = { }
    associations = { }
    associationends = { }
    attributes = { }
    for key, val in all_elements.items():
        # Find classes, *Kind (enumerations) are given special treatment
        if isinstance(val, element):
            if val.type == 'Class' and val.get('name'):
                if val['name'].endswith('Kind'):
                    enumerations[key] = val
                else:
                    classes[key] = val
                    # Add extra properties for easy code generation:
                    val.specialization = []
                    val.generalization = []
                    val.written = False
            elif val.type == 'Generalization':
                generalizations[key] = val
            elif val.type == 'Association':
                associations[key] = val
            elif val.type == 'AssociationEnd':
                associationends[key] = val
            elif val.type == 'Attribute':
                attributes[key] = val

    # find inheritance relationships
    for n in classes.values():
        for id in n.get('specialization') or ():
            # traverse the generalization object:
            refids = generalizations[id]['child']
            assert len(refids) == 1
            n.specialization.append(classes[refids[0]])
        for id in n.get('generalization') or ():
            # traverse the generalization object:
            refids = generalizations[id]['parent']
            assert len(refids) == 1
            n.generalization.append(classes[refids[0]])

    # create file header
    out.write(header)

    # do not create a class definition for Element, since it is imported:
    filter(lambda c: c['name'] == 'Element', classes.values())[0].written = True

    # create class definitions
    for c in classes.values():
        write_classdef(c, out)

    # create attributes and enumerations
    for c in classes.values():
        for f in c.get('feature') or ():
            a = attributes.get(f)
            if a:
                kind, derived, name, type, default, lower, upper = parse_attribute(a)
                #if derived:
                #    out.write('# derived: ')
                if not derived and kind == ATTRIBUTE:
                    out.write("%s.%s = attribute('%s', %s, %s, %s, %s)\n" %
                              (c['name'], name, name, type, default, lower, upper))
                elif kind == ENUMERATION:
                    e = filter(lambda e: e['name'] == type, enumerations.values())[0]
                    values = [ ]
                    for key in e['feature']:
                        values.append(str(attributes[key]['name']))
                    out.write("%s.%s = enumeration('%s', %s, '%s')\n" %
                              (c['name'], name, name, tuple(values),
                               default or values[0]))

    # create associations, derivedunions are held back
    derivedunions = { } # indexed by name in stead of id
    redefines = [ ]
    for a in associations.values():
        end1, end2 = a['connection']
        end1 = associationends[end1]
        end2 = associationends[end2]
        end1.participant = classes[end1['participant'][0]]
        end2.participant = classes[end2['participant'][0]]
        for e1, e2 in ((end1, end2), (end2, end1)):
            if not write_association(out, e1, e2):
                # assure that derived unions do not get overwritten
                if e1.redefines:
                    redefines.append(e1)
                else:
                    assert not derivedunions.get(e1.name)
                    derivedunions[e1.name] = e1
                    e1.union = [ ]
                    e1.written = False

    # create derived unions, first link the association ends to the d
    for a in filter(lambda e: hasattr(e, 'subsets'), associationends.values()):
        for s in a.subsets:
            try:
                derivedunions[s].union.append(a)
            except KeyError:
                # We should create a derived union for the 
                msg('Not a derived union: %s' % s)

    for d in derivedunions.values():
        write_derivedunion(d, out)

    for r in redefines:
        msg('redefine %s to %s.%s' % (r.redefines, r.class_name, r.name))
        write_redefine(r, out)

    if outfile:
        out.close()

if __name__ == '__main__':
    generate('UML2.gaphor')

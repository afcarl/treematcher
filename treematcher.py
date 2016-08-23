#system modules
import re
from itertools import permutations

# third party modules
import ast
import six
from ete3 import PhyloTree, Tree, NCBITaxa

# internal modules
# ...


class TreePatternCache(object):
    def __init__(self, tree):
        """ Creates a cache for attributes that require multiple tree
        traversal when using complex TreePattern queries.

        :param tree: a regular ETE tree instance
         """
        # Initialize cache (add more stuff as needed)
        self.leaves_cache = tree.get_cached_content()
        self.all_node_cache = tree.get_cached_content(leaves_only=False)

    def get_cached_attr(self, attr_name, node, leaves_only=False):
        """
        easy access to cached attributes on trees.

        :param attr_name: any attribute cached in tree nodes (e.g., species,
         name, dist, support, etc.)

        :param node: The pattern tree containing the cache

        :leaves_only: If True, return cached values only from leaves

        :return: cached values for the requested attribute (e.g., Homo sapiens,
         Human, 1.0, etc.)

        """
        #print("USING CACHE")
        cache = self.leaves_cache if leaves_only else self.all_node_cache
        values = [getattr(n, attr_name, None) for n in cache[node]]
        return values

    def get_leaves(self, node):
        return self.leaves_cache[node]

    def get_descendants(self, node):
        return self.all_node_cache[node]


class _FakeCache(object):
    """TreePattern cache emulator."""
    def __init__(self):
        pass

    def get_cached_attr(self, attr_name, node, leaves_only=False):
        """ Helper function to mimic the behaviour of a cache, so functions can
        refer to a cache even when one has not been created, thus simplifying code
        writing. """
        if leaves_only:
            iter_nodes = node.iter_leaves
        else:
            iter_nodes = node.traverse

        values = [getattr(n, attr_name, None) for n in iter_nodes()]
        return values

    def get_leaves(self, node):
        return node.get_leaves()

    def get_descendants(self, node):
        return node.get_descendants()


class PatternSyntax(object):
    def __init__(self):
        # Creates a fake cache to ensure all functions below are functioning
        # event if no real cache is provided
        self.__fake_cache = _FakeCache()
        self.__cache = None

    def __get_cache(self):
        if self.__cache:
            return self.__cache
        else:
            return self.__fake_cache

    def __set_cache(self, value):
        self.__cache = value

    cache = property(__get_cache, __set_cache)

    def leaves(self, target_node):
        return sorted([name for name in self.cache.get_cached_attr(
            'name', target_node, leaves_only=True)])

    def descendants(self, target_node):
        return sorted([name for name in self.cache.get_cached_attr(
            'name', target_node)])

    def species(self, target_node):
        return set([name for name in self.cache.get_cached_attr(
            'species', target_node, leaves_only=True)])

    def contains_species(self, target_node, species_names):
        """
        Shortcut function to find the species at a node and any of it's descendants.
        """
        if isinstance(species_names, six.string_types):
            species_names = set([species_names])
        else:
            species_names = set(species_names)

        found = 0
        for sp in self.cache.get_cached_attr('species', target_node, leaves_only=True):
            if sp in species_names:
                found += 1
        return found == len(species_names)

    def contains_leaves(self, target_node, node_names):
        """ Shortcut function to find if a node contains at least one of the
        node names provided. """

        if isinstance(node_names, six.string_types):
            node_names = set([node_names])
        else:
            node_names = set(node_names)

        found = 0
        for name in self.cache.get_cached_attr('name', target_node, leaves_only=True):
            if name in node_names:
                found += 1
        return found == len(node_names)

    def n_species(self, target_node):
        """ Shortcut function to find the number of species within a node and
        any of it's descendants. """

        species = self.cache.get_cached_attr('species', target_node, leaves_only=True)
        return len(set(species))

    def n_leaves(self, target_node):
        """ Shortcut function to find the number of leaves within a node and any
                of it's descendants. """
        return len(self.cache.get_leaves(target_node))

    def n_duplications(self, target_node):
        """
            Shortcut function to find the number of duplication events at or below a node.
            :param target_node: Node to be evaluated, given as @.
            :return: True if node is a duplication, otherwise False.
        """
        events = self.cache.get_cached_attr('evoltype', target_node)
        return(events.count('D'))

    def n_speciations(self, target_node):
        """
            Shortcut function to find the number of speciation events at or below a node.
        """
        events = self.cache.get_cached_attr('evoltype', target_node)
        return(events.count('S'))


    # TODO: review next function

    def smart_lineage(self, constraint):
        """ Get names instead of tax ids if a string is given before the "in
        @.linage" in a query. Otherwise, returns Taxonomy ids. Function also
        works for constraint that contains something besides the given target
        node (e.g., @.children[0].lineage).

        :param constraint: Internal use.

        :return:  Returns list of lineage tax ids if taxid is searched,
        otherwise returns names in lineage. """

        parsedPattern = ast.parse(constraint, mode='eval')

        lineage_node = [n for n in ast.walk(parsedPattern)
                        if hasattr(n, 'comparators') and type(n.comparators[0]) == ast.Attribute
                        and n.comparators[0].attr == "lineage"]

        index = 0
        for lineage_search in lineage_node:
            if hasattr(lineage_node[index].left,'s'):
                # retrieve what is between __target and .lineage
                found_target = (re.search(r'__target[^ ]*\.lineage', constraint).span())
                extracted_target = constraint[found_target[0]: found_target[1]]

                syntax = "(ncbi.get_taxid_translator(" + \
                         str(extracted_target) + ")).values()"
                if index == 0:
                    constraint = constraint.replace(str(extracted_target), syntax, 1)
                else:

                    constraint = re.sub(r'^((.*?' + extracted_target + r'.*?){' + str(index) + r'})' + extracted_target,
                             r'\1' + syntax, constraint)

            index += 1

        return constraint


class TreePattern(Tree):
    def __str__(self):
        return self.get_ascii(show_internal=True, attributes=["name"])

    def __init__(self, newick=None, format=1, dist=None, support=None,
                 name=None, quoted_node_names=True, syntax=None):
        """ Creates a tree pattern instance that can be used to search within
        other trees.

        :param newick: Path to the file containing the tree or, alternatively,
            the text string containing the same information.
        :param format: subnewick format that is a number between 0 (flexible)
            and 9 (leaf name only), or 100 (topology only).
        :param quoted_node_names: Set to True if node names are quoted with
            stings, otherwise False.
        :syntax: Syntax controller class containing functions to use as
            constraints within the pattern.
        """
        # Load the pattern string as a normal ETE tree, where node names are
        # python expressions
        super(TreePattern, self).__init__(newick, format, dist, support, name, quoted_node_names)

        # Set a default syntax controller if a custom one is not provided
        self.syntax = syntax if syntax else PatternSyntax()

    # FUNCTIONS EXPOSED TO USERS START HERE
    def match(self, node, cache=None):
        """
        Check all constraints interactively on the target node.

        :param node: A tree (node) to be searched for a given pattern.

        :param local_vars:  Dictionary of TreePattern class variables and
        functions for constraint evaluation.

        :return: True if a match has been found, otherwise False.
        """
        self.syntax.cache = cache
        # does the target node match the root node of the pattern?
        status = self.is_local_match(node, cache)

        # if so, continues evaluating children pattern nodes against target node
        # children
        if status and self.children:

                # print("Now checking Children")
                if len(node.children) >= len(self.children):
                    # If pattern node expects children nodes, tries to find a
                    # combination of target node children that match the pattern
                    for candidate in permutations(node.children):
                        sub_status = True
                        for i in range(len(self.children)):
                            st = self.children[i].match(candidate[i], cache)
                            if st is not None:
                                sub_status &= st
                        status = sub_status
                        if status:
                            break
                else:
                    status = False

        return status

    def cascade_match(self, node, cache=None):
        """
        Check all constraints interactively on the target node.

        :param node: A tree (node) to be searched for a given pattern.

        :param local_vars:  Dictionary of TreePattern class variables and
        functions for constraint evaluation.

        :return: True if a match has been found, otherwise False.
        """
        self.syntax.cache = cache
        # does the target node match the root node of the pattern?
        status = self.is_local_match(node, cache)
        print("Matching target node {} to pattern node {}?".format(node.name, self.name))
        print("status is {}".format(status))

        # if so, continues evaluating children pattern nodes against target node
        # children
        matched_nodes = []
        if status:
            if self.name != '*':
                matched_nodes += [node]
            if self.children:
                print("node children are {}".format(node.children))

                print("Now checking Children")
                if len(node.children) >= len(self.children):
                    # If pattern node expects children nodes, tries to find a
                    # combination of target node children that match the pattern
                    for candidate in permutations(node.children):
                        sub_status = True
                        sub_nodes = []
                        for i in range(len(self.children)):
                            st, self, sub_sub_nodes = self.children[i].cascade_match(candidate[i], cache)
                            print("Child status is {}".format(st))
                            if st is not None:
                                sub_status &= st
                            sub_nodes += sub_sub_nodes

                        status = sub_status
                        matched_nodes += sub_nodes
                        if status:
                            break
                else:
                    print("Pattern has more children than target")
                    if self.name == '*':
                        sub_status = True
                        sub_nodes = []
                        for i in range(len(self.children)):
                            #print("Checking last pattern node")
                            st, self, sub_sub_nodes = self.children[i].cascade_match(node, cache)
                            print("Second child status is {}".format(st))
                            sub_status &= st
                            sub_nodes += sub_sub_nodes
                        status = sub_status
                        matched_nodes += sub_nodes
                    else:
                        status = False

        self.syntax.cache = None
        return status, self, matched_nodes

    def is_local_match(self, target_node, cache):
        """ Evaluate if this pattern constraint node matches a target tree node.

        TODO: args doc here...
        """

        # Creates a local scope containing function names, variables and other
        # stuff referred within the pattern expressions. We use Syntax() as a
        # container of those custom functions and shortcuts.

        constraint_scope = {attr_name: getattr(self.syntax, attr_name)
                            for attr_name in dir(self.syntax)}
        constraint_scope.update({"__target_node": target_node})

        if not self.name:
            # empty pattern node should match any target node
            constraint = ''
        elif '@' in self.name:
            # converts references to node itself
            constraint = self.name.replace('@', '__target_node')
        elif '*' == self.name:
            # star pattern node should match any target node
            constraint = ''

        else:
            # if no references to itself, let's assume we search an exact name
            # match (allows using regular newick string as patterns)
            constraint = '__target_node.name == "%s"' % self.name

        try:
            st = eval(constraint, constraint_scope) if constraint else True
            # if isinstance(st, six.string_types):
            #     raise ValueError
            # else:
            #     st = bool(st)  # all sets return true

        except ValueError:
            #raise ValueError("not a boolean result: %s. Check quoted_node_names." %
            #                 (st))
            raise ValueError("not a boolean result: . Check quoted_node_names.")

        except (AttributeError, IndexError) as err:
            raise ValueError('Constraint evaluation failed at %s: %s' %
                             (target_node, err))
        except NameError:
            try:
                # temporary fix. Can not access custom syntax on all nodes. Get it from the root node.
                root_syntax = self.get_tree_root().syntax
                # print("root_syntax is ", root_syntax)
                constraint_scope = {attr_name: getattr(root_syntax, attr_name)
                                    for attr_name in dir(root_syntax)}
                constraint_scope.update({"__target_node": target_node})

                st = eval(constraint, constraint_scope) if constraint else True

                # if isinstance(st, six.string_types):
                #    raise ValueError
                # else:
                #    st = bool(st)  # all sets return true
                return st
            except NameError as err:
                raise NameError('Constraint evaluation failed at %s: %s' %
                         (target_node, err))
        else:
            # self.syntax.__cache = None
            return st

    def find_match(self, tree, maxhits=1, cache=None, target_traversal="preorder", match_type=None):
        """ A pattern search continues until the number of specified matches are
        found.
        :param tree: tree to be searched for a matching pattern.
        :param maxhits: Number of matches to be searched for.
        :param cache: When a cache is provided, preloads target tree information
                               (recommended only for large trees)
        :param None maxhits: Pattern search will continue until all matches are found.
        :param target_traversal: choose the traversal order (e.g. preorder, levelorder, etc)
        :param nested: for each match returned,

        """


        if match_type=="cascade":
            # initialize variables
            match_found=0
            matched_root_node = None # The root node of the target tree that matches the pattern
            pattern_length = len(self.get_descendants())  # length excluding root, might want to add a +1?
            current_pattern_node = self
            count = 0
            num_hits = 0

            while pattern_length <= len(tree.get_descendants()) and count<=5: # when to break when match not found? Depends on target size minus # stars?
                print("############## Matched_root_node is {}".format(matched_root_node))
                # reset variables and start over
                if matched_root_node == None:
                    if count!=0: # if no match found on first pattern node in first round, break
                        break
                else:
                    # break matched root node from the tree, there was no match found in the subtree
                    print("resetting tree and pattern")
                    matched_root_node.detach()
                    matched_root_node = None  # The first node in the list that matches to the root of the pattern
                count+=1
                current_pattern_node = self  # start over on tree without previous node

                # length excluding root, might want to add a +1?
                print("pattern length is: {}".format(pattern_length))
                print("tree length is: {}".format(len(tree.get_descendants())))



                for node in tree.traverse("preorder"):
                    status, pattern_node, matched_nodes = current_pattern_node.cascade_match(node, cache)
                    if matched_root_node == None:
                        if matched_nodes:
                            matched_root_node = matched_nodes[0]


                    #matched_node_set.update(matched_nodes)
                    print("matched_nodes are: {}".format(matched_nodes))
                    #print("############ matched_nodes are: {}".format(matched_node_set))

                    if current_pattern_node != pattern_node: # we have already matches up to this point
                        current_pattern_node = pattern_node

                    if status:
                        num_hits += 1
                        print("yeilding matched node list: {}".format(matched_root_node))
                        #match found

                        if matched_nodes[-1] in matched_root_node:
                            yield matched_root_node #yield status only when a full match is found
                            match_found = 1
                        else:
                            print("no dice")
                            match_found = 0
                        break

                    #if numhits >= pattern_length:
                    if num_hits >= pattern_length:
                        break

        else:

            num_hits = 0
            for node in tree.traverse(target_traversal):
                if self.match(node, cache):
                    num_hits += 1
                    yield node
                if maxhits is not None and num_hits >= maxhits:
                    break





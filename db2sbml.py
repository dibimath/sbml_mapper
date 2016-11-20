


#import sys
#import os.path
import sqlite3
import libsbml
#from libsbml import *
import re

def writeDBModelToSBML(database_path, sbml_output_path, modelRow=1):

    # Create the connection to the SQLite model database
    conn = sqlite3.connect(database_path) # TO DO: exception for failed connection
    c = conn.cursor()

    # Create an SBMLNamespaces object with the given SBML level, version
    # package name, package version.
    sbmlns = libsbml.SBMLNamespaces(3, 1, "qual", 1)
    # Creates an SBMLDocument object
    document = libsbml.SBMLDocument(sbmlns)
    # mark qual as required
    document.setPackageRequired("qual", True)
    # create the Model
    model = document.createModel()

    # Get a QualModelPlugin object plugged in the model object.
    mplugin = model.getPlugin("qual")

    # Extract regulatory context descriptions from table Parametrizations
    column_name_list = [tuple[0] for tuple in c.execute("SELECT * FROM Parametrizations").description] # TO DO: exception for invalid/missing model

    #print([column_name[0:2] for column_name in column_name_list])
    context_name_list = [column_name for column_name in column_name_list if column_name[0:2] == 'K_'] # TO DO: index dependent = bad

    #parameter_list = list(c.execute('SELECT ' + ', '.join(context_name_list) + ' FROM Parametrizations WHERE rowid=' + str(modelRow)).fetchall()) # TO DO: depends on single row/unique ID

    target_list = [target for target, in c.execute('SELECT DISTINCT Target FROM Regulations ORDER BY Target').fetchall()]
    context_list = []
    for context_name in context_name_list:
        target_match_list = [target for target in target_list if context_name[2:].find(target) != -1] # can find multiple e.g. context_name=RafB will match species Raf and RafB
        target = [match for match in target_match_list if len(match) == max(map(len, target_match_list))][0] # take longest match, TO DO: check if single match?
        pattern = r'(?<=K_{0}_)\d+'.format(target)
        thresholds_name = re.search(pattern, context_name).group(0) # TO DO: check if length >= 1 ?
        threshold_list = [int(d) for d in thresholds_name] # TO DO: what about double digit thresholds? --> exception or ignore
        context = [context_name, target]
        context.extend(threshold_list) # each context = list of format [K_Raf_031, Raf, 0, 3, 1]
        context_list.append(context)

    # write to qualSBML model

    # set QualitativeSpecies from Components table
    for name, maxActivity in c.execute('SELECT Name, MaxActivity FROM Components ORDER BY Name').fetchall():
        # create a qualSBML QualitativeSpecies
        qs = mplugin.createQualitativeSpecies()
        qs.setId(name)
        qs.setConstant(False)
        qs.setMaxLevel(maxActivity)
        #qs.setName(name)

    # set Transitions from Regulations and Parametrizations tables
    for target, in c.execute('SELECT DISTINCT Target FROM Regulations ORDER BY Target').fetchall():
        # create a Transition: one qualSBML Transition per TREMPPI component with >= 1 regulators
        t = mplugin.createTransition()
        # create qualSBML transition output
        o = t.createOutput()
        o.setQualitativeSpecies(target)
        o.setTransitionEffect(1) # transitionEffect='assignmentLevel'

        # save a list of all regulator/input-species-names (string) for this target component
        source_list = []

        for source, in c.execute('SELECT DISTINCT Source FROM Regulations WHERE Target=? ORDER BY Source', (target,)).fetchall():
            # create qualSBML transition input
            i = t.createInput()
            i.setQualitativeSpecies(source)
            i.setTransitionEffect(0) # transitionEffect='none'
            # also append this input to our regulator/input-name list
            source_list.append(source)

        # setup a ASTNode representation for  the qualSBML Transition.FunctionTerm.Math element from TREMPPI regulatory context information

        # get all regulatory contexts for this target component
        target_context_list = [context for context in context_list if context[1] == target]

        # each regulatory context is represented in qualSBML by one Transition.FunctionTerm or by the Transition.DefaultTerm
        for context in target_context_list:
            # list of regulator threshold states for this context
            source_tstate_list = context[2:]
            # parameter target value of this context
            #param = c.execute('SELECT ' + context[0] + ' FROM Parametrizations WHERE rowid=' + str(modelRow), (context[0], modelRow)).fetchall()[0][0]
            param = c.execute('SELECT {0} FROM Parametrizations WHERE rowid=?'.format(context[0]), (modelRow,) ).fetchall()[0][0]

            # if this context is the context with threshold level = 0 for all regulators, use it as Transition.DefaultTerm in qualSBML
            if sum(source_tstate_list) == 0:
                d = t.createDefaultTerm()
                d.setResultLevel(param)

            # else create a Transition.FunctionTerm term with math element
            else:
                f = t.createFunctionTerm()
                f.setResultLevel(param)

                # list of the ASTNode-tree inequality representations of each regulator
                f_ASTNode_list = []

                # find lower and upper thresholds (activity interval) of each regulator in this context and build an ASTNode tree of the resulting inequalities
                for source_index in range(0, len(source_list)-1):
                    source = source_list[source_index]
                    source_tstate = source_tstate_list[source_index]
                    threshold_list, = c.execute('SELECT Threshold FROM Regulations WHERE Target=? AND Source=? ORDER BY Threshold', (target, source)).fetchall()
                    lower_t = 0
                    leftmost = True
                    upper_t = threshold_list[0]
                    rightmost = False
                    threshold_index = 0
                    while source_tstate > lower_t:
                        lower_t = threshold_list[threshold_index]
                        threshold_index += 1
                        leftmost = False
                    if len(threshold_list) > threshold_index:
                        upper_t = threshold_list[threshold_index]
                    else:
                        upper_t = c.execute('SELECT MaxActivity FROM Components WHERE Name=?', (source,)).fetchall()[0]
                        rightmost = True

                    # build ASTNode tree
                    source_ASTNode = libsbml.ASTNode(libsbml.AST_NAME)
                    source_ASTNode.setName(source)

                    if leftmost:
                        ast = libsbml.ASTNode(libsbml.AST_RELATIONAL_LT)
                        threshold_ASTNode = libsbml.ASTNode(libsbml.AST_INTEGER)
                        threshold_ASTNode.setValue(upper_t)
                        ast.addChild(libsbml.ASTNode(source_ASTNode))
                        ast.addChild(threshold_ASTNode)
                    elif rightmost:
                        ast = libsbml.ASTNode(libsbml.AST_RELATIONAL_GT)
                        threshold_ASTNode = libsbml.ASTNode(libsbml.AST_INTEGER)
                        threshold_ASTNode.setValue(lower_t)
                        ast.addChild(libsbml.ASTNode(source_ASTNode))
                        ast.addChild(threshold_ASTNode)
                    else:
                        ast = libsbml.ASTNode(libsbml.AST_LOGICAL_AND)

                        lower_t_ASTNode = libsbml.ASTNode(libsbml.AST_RELATIONAL_GT)
                        threshold_ASTNode = libsbml.ASTNode(libsbml.AST_INTEGER)
                        threshold_ASTNode.setValue(lower_t)
                        lower_t_ASTNode.addChild(libsbml.ASTNode(source_ASTNode))
                        lower_t_ASTNode.addChild(threshold_ASTNode)

                        upper_t_ASTNode = libsbml.ASTNode(libsbml.AST_RELATIONAL_LT)
                        threshold_ASTNode = libsbml.ASTNode(libsbml.AST_INTEGER)
                        threshold_ASTNode.setValue(upper_t)
                        upper_t_ASTNode.addChild(libsbml.ASTNode(source_ASTNode))
                        upper_t_ASTNode.addChild(threshold_ASTNode)

                        ast.addChild(lower_t_ASTNode)
                        ast.addChild(upper_t_ASTNode)

                    f_ASTNode_list.append(ast)

                if(len(f_ASTNode_list) > 1):
                    topASTNode = libsbml.ASTNode(libsbml.AST_LOGICAL_AND)
                    for ast in f_ASTNode_list:
                        topASTNode.addChild(ast)
                else:
                    topASTNode = f_ASTNode_list[0]

                f.setMath(topASTNode)

    libsbml.writeSBML(document, sbml_output_path)


writeDBModelToSBML('database.sqlite', 'db2sbmp_output.xml', modelRow=3)















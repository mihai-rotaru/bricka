#!/usr/bin/env python
# encoding: utf-8

"""
A waf tool for minifying javascript.
(http://code.google.com/p/htmlcompressor)
"""

import os
import re
from hashlib import md5
from HTMLParser import HTMLParser

from waflib.Task import Task
from waflib.TaskGen import extension, after_method, before_method
from waflib import Logs, Errors, Utils

# return hex MD5 digest of `file`
#-------------------------------------------------------------------------------
def h_file_hex( fname ):
	f = open( fname,'rb' )
	m = md5()
	try:
		while fname:
			fname=f.read( 200000 )
			m.update( fname )
	finally:
		f.close()
	return m.hexdigest()

# use ClosureCompiler to minify a JavaScript file
#-------------------------------------------------------------------------------
class minify_js( Task ):
    color = 'CYAN'
    run_str = 'java -jar ${closure_compiler} ${jsminifier_options} --js ${SRC} --js_output_file ${TGT}'

# generate new HTML file, with script tags pointing to the generated minified versions
#-------------------------------------------------------------------------------
class update_html( Task ):
    color = 'PINK'
    after = [ 'minify_js' ]

    def myfunc( self ):
        on = self.outputs[0]
        new_html_contents = replace_scripts( self.html_contents, self.tasks )
        on.write( new_html_contents )

    def run( self ):
        return self.myfunc()

# `data` - the contents of the HTML file; `tasks` - minificatino tasks. Each
# task has the position in the HTML data where the script tag is mentioned.
# This informaiton is used in this function to update `script` tags to point to
# the minified version of each script. Only tasks that have successfully ran
# are considered.
#-------------------------------------------------------------------------------
def replace_scripts( data, tasks ):
    lines = data.split('\n')
    for task in tasks:
        if task.hasrun == 9: # if task was run successfully; i.e. minification succeeded
            line_no = task.html_position[0]
            Logs.debug( 'processing replacement task: ' + task.outputs[0].nice_path() + ' on line ' + str(line_no) )
            old = task.inputs[0].nice_path().replace( '\\', '/' )
            new = task.outputs[0].relpath()
            Logs.debug( 'replacing "%s" with "%s" in %s', old, new, task.outputs[0].abspath() )
            lines[ line_no-1 ] = lines[ line_no-1 ].replace( old, new )
            Logs.debug( 'new line: ' + lines[ line_no-1 ] )
    data = '\n'.join(lines)
    return data

# from: http://stackoverflow.com/a/11659969/447661
#-------------------------------------------------------------------------------
def read_entirely( file ):
    with open( file, 'r' ) as handle:
        return handle.read()

# scan an HTML file to detect referenced JavaScript files
#-------------------------------------------------------------------------------
class Gather_HTMLParser( HTMLParser ):

    # regex to detect local fallback for failed CDN requests ( JQuery only )
    inline_js_regex         = re.compile( r'window\.(?i)jquery\s*\|\|\s*document.write\(([\'"])\s*<script\s*src=([\'"])(?P<src>.*?)\2\s*(?:type=\2text/javascript\2\s*)?><\\/script>\1\)' )

    # regexes for CDNs
    google_cdn_regex        = re.compile( r'//ajax.googleapis.com/ajax/libs/(.*?)/(.*?)/(.*)\.js' )
    microsoft_cdn_regex     = re.compile( r'//ajax.aspnetcdn.com/ajax/(.*?)/(.*)\.js' )
    cdnjs_cdn_regex         = re.compile( r'//cdnjs.cloudflare.com/ajax/libs/(.*?)/(.*?)/(.*)\.js' )

    # each detected js file will be added to this list
    local_scripts = []

    # each detected CDN js file will be added to this list
    cdn_scripts = []

    # find referenced js files
    def handle_starttag( self, tag, attrs ):
        if( tag == 'script' ):
            for name,value in attrs:
                if( name == 'src' ):
                    if(     self.google_cdn_regex.search( value ) or
                            self.microsoft_cdn_regex.search( value ) or
                            self.cdnjs_cdn_regex.search( value ) ):
                        self.cdn_scripts.append( value )
                        Logs.warn( 'minify: ignoring CDN script: %s' % value )
                    else:
                        local_script = []
                        local_script.append( self.getpos() )
                        local_script.append( value )
                        self.local_scripts.append( local_script )

@extension( '.html' )
def html_hook( self, node ):

    # scan the HTML file for script tags
    parser = Gather_HTMLParser()
    html_contents = read_entirely( node.abspath() )
    parser.feed( html_contents )
    scripts = parser.local_scripts

    # create a minification task for scripts that are local
    for script_tuple in scripts:
        script = script_tuple[1]
        if( not script.endswith('.min.js') ):
            script_node = self.bld.path.find_resource( script )
            if( script_node ):
                src_md5 = h_file_hex( script_node.abspath() )
                tgt = script_node.change_ext( '.' + src_md5[:7] + '.min.js' )
                tsk = self.create_task( 'minify_js', script_node, tgt )
                tsk.html_position = script_tuple[0]
            else:
                Logs.warn( 'minify: script referenced in %s not found: %s' % (node.abspath(), script) )
        else:
            Logs.warn( 'minify: ignoring %s because it\'s filename suggests it is already minified.' % script )
    
    # generate a task for creating the new HTML file, with script tags pointing to
    # the generated minified versions. This task will have a 'tasks' attribute, a
    # list of all the minification tasks. `tasks` will be used to update the HTML
    # only for successfull minifications.
    update_html_task = self.create_task( 'update_html', node, node.get_bld() )
    update_html_task.tasks = self.tasks[:-1]
    update_html_task.html_contents = html_contents

def configure( conf ):
    conf.env['closure_compiler'] = os.path.abspath( conf.find_file( 'closure-compiler-v1346.jar', ['.','./tools' ] ) )

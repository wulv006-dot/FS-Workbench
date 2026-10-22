"""Four exact static targets through the existing reviewed CAS publisher."""
SCOPE='fs-business-procurement-20261022'
VERSION='business-procurement-20261022-fb8814af4a60'
PREFIX='releases/fs-dashboard/business-procurement-20261022/'
SOURCES={f'ui/{name}':PREFIX+'source/'+name for name in ('business.js','home-business.js','legacy-business.js')}
TARGETS={relative:'/var/lib/fs-navigation-formal-static/'+VERSION+'/'+relative.split('/')[-1] for relative in SOURCES}
TARGETS['generated/navigation.conf']='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
ALIASES={
 '/var/lib/fs-navigation-formal-static/workspace-native-20261006-8b7908ecad30/business.js':'business.js',
 '/var/lib/fs-navigation-formal-static/workspace-native-20261006-72d7ba0dbca8/business.js':'home-business.js',
 '/var/lib/fs-navigation-formal-static/workspace-native-20261006-fd4cfd0a70aa/business.js':'legacy-business.js'}

def candidate(before):
    result=before
    for old,name in ALIASES.items():
        needle=('alias '+old+';').encode()
        if before.count(needle)!=1:raise ValueError('exact_active_business_alias_required')
        result=result.replace(needle,('alias /var/lib/fs-navigation-formal-static/'+VERSION+'/'+name+';').encode(),1)
    return result

def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(SOURCES)
    return release.load_base()

if __name__=='__main__':load_base().main()

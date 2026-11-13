import json, sys
d = json.load(open('docs/research/T-376_probe_gaps.json'))
R = {r['name']: r for r in d['results']}
names = sys.argv[1:] or list(R)
for n in names:
    r = R[n]
    print('==', n, r.get('status'))
    for k in ('points','date_first','date_last','ts_first','ts_last','v_first','v_last',
              'c_first','c_last','days_len','day0','day_last','keys','list_len',
              'llama_urls_in_html','data_api_paths_in_html','build_id','top_keys','sample',
              'data0_keys','item0_keys','events','per_min','error','code_msg','code_status'):
        if k in r:
            print('   ', k, '=', str(r[k])[:400])
    print('   first200:', (r.get('first200') or '')[:220].replace('\n', ' | '))

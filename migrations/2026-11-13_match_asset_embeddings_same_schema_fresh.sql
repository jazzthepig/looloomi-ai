-- S-842 (2026-11-13): match_asset_embeddings 只在同一个 schema_version、且没有停更的行里找近邻。
--
-- 实测:asset_embeddings 73 行里 14 行停在 2026-07-24(schema_version 2,18 维;这些币已不在打分面板里),
-- 其余 59 行是 schema_version 3、每天更新。函数原来不看这两列 —— 两套坐标系的向量放在同一个余弦里比。
-- 今天的后果是 0(59 个在更新的目标,k = 5 与 k = 20 的近邻里都没有一行停更的:两套坐标本来就离得远),
-- 但拿一个停更的币当目标,返回的是 v3 的邻居,没有意义;面板再换一次 schema 时也不该靠「离得远」来隔离。
-- 新鲜度是相对的(对表里最新一次写入 7 天内):整张表停更时不返回空 —— 那是 vdb_health 的事,不是这个函数的事。
-- 签名不变;不删任何行。回滚 = 去掉下面标 S-842 的两行条件。
create or replace function public.match_asset_embeddings(target text, k integer default 5, class_mode text default 'any'::text)
 returns table(symbol text, asset_class text, macro_regime text, cosine_sim double precision)
 language sql
 stable
 set search_path to 'public', 'pg_temp'
as $function$
  with t as (select vec, asset_class tc, schema_version sv from asset_embeddings where symbol = target and vec is not null),
       f as (select max(computed_at) - interval '7 days' cut from asset_embeddings)
  select e.symbol, e.asset_class, e.macro_regime,
         (1 - (e.vec <=> t.vec))::double precision as cosine_sim
  from asset_embeddings e, t, f
  where e.symbol <> target and e.vec is not null
    and e.schema_version = t.sv            -- S-842
    and e.computed_at >= f.cut             -- S-842
    and ( class_mode = 'any'
       or (class_mode = 'same'  and e.asset_class = t.tc)
       or (class_mode = 'cross' and e.asset_class is distinct from t.tc) )
  order by e.vec <=> t.vec
  limit k;
$function$;

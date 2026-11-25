-- Copy-paste dashboard queries (`wrangler d1 execute uta-learn-next-stats --remote --command "..."`).

-- 日活
SELECT day, COUNT(DISTINCT iid) AS dau FROM pings GROUP BY day ORDER BY day DESC LIMIT 30;

-- 周活 / 月活
SELECT COUNT(DISTINCT iid) AS wau FROM pings WHERE day >= date('now', '-7 day');
SELECT COUNT(DISTINCT iid) AS mau FROM pings WHERE day >= date('now', '-30 day');

-- 新增安装（某个 iid 第一次出现的那天）
SELECT first_day, COUNT(*) AS new_installs FROM (
  SELECT iid, MIN(day) AS first_day FROM pings GROUP BY iid
) GROUP BY first_day ORDER BY first_day DESC LIMIT 30;

-- 版本分布（最近 7 天）
SELECT v, COUNT(DISTINCT iid) AS installs
FROM pings WHERE day >= date('now', '-7 day')
GROUP BY v ORDER BY installs DESC;

-- 系统分布（最近 30 天）
SELECT os, COUNT(DISTINCT iid) AS installs
FROM pings WHERE day >= date('now', '-30 day')
GROUP BY os ORDER BY installs DESC;

-- 保留 400 天原始数据
DELETE FROM pings WHERE day < date('now', '-400 day');

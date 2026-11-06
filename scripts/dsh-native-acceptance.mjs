// The TUI receipt check, lines 204-238 of northstar@b384d298d217d3f8d9aa83356994629536a34795:
// scripts/dsh-native-acceptance.mjs, verbatim, with its --tui command line. Its web, ws and synthesis
// modes need northstar's own installer and are not carried. Reads only the names-only startup log.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {startupLogPath,validateTuiStartup} from '../config/dsh/native-startup.mjs';
// TUI stays attached to Orca's real PTY, not a substitute headless process or
// web listener. Consume its existing names-only startup diagnostic explicitly;
// this observer never starts a runtime or reads any upstream sign-in state.
export function acceptNativeDshTui({diagnostic,log,home=process.env.HOME}={}){
  let logPid;
  if(log){
    home=fs.realpathSync(home);
    const directory=path.dirname(startupLogPath(home)),match=/^native-startup-([1-9][0-9]*)\.log$/.exec(path.basename(log));
    if(!path.isAbsolute(log)||path.dirname(log)!==directory||!match)throw new Error('DSH_ACCEPT_TUI_LOG_INVALID');
    logPid=Number(match[1]);
    for(let current=directory;current!==home;current=path.dirname(current)){
      const parent=fs.lstatSync(current);
      if(!parent.isDirectory()||parent.isSymbolicLink()||parent.uid!==process.getuid())throw new Error('DSH_ACCEPT_TUI_LOG_INVALID');
    }
    const stat=fs.lstatSync(log);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.uid!==process.getuid()||stat.nlink!==1||(stat.mode&0o777)!==0o600||stat.size>65536)
      throw new Error('DSH_ACCEPT_TUI_LOG_INVALID');
    const fd=fs.openSync(log,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
    try{
      const opened=fs.fstatSync(fd);
      if(opened.ino!==stat.ino||opened.dev!==stat.dev)throw new Error('DSH_ACCEPT_TUI_LOG_CHANGED');
      const line=fs.readFileSync(fd,'utf8').trim();
      if(!line.startsWith('northstar-dsh-startup '))throw new Error('DSH_ACCEPT_TUI_LOG_INVALID');
      diagnostic=JSON.parse(line.slice('northstar-dsh-startup '.length));
    }finally{fs.closeSync(fd);}
  }
  if(diagnostic?.schemaVersion!==2||diagnostic.profile!=='tui'||!Number.isInteger(diagnostic.pid)||diagnostic.pid<=0||logPid!==undefined&&diagnostic.pid!==logPid||
    !Number.isFinite(Date.parse(diagnostic.startedAt))||!validateTuiStartup(diagnostic.tui))
    throw new Error('DSH_ACCEPT_TUI_INVENTORY_FAILED: missing receipt fields, OAuth/held provider loaded, or approved provider not active');
  const value=diagnostic.tui;
  return {result:'PASS',profile:'tui',pid:diagnostic.pid,startedAt:new Date(diagnostic.startedAt).toISOString(),
    overlays:[...value.overlays],providers:Object.keys(value.providers),holds:value.holds.map(({id})=>id),openviking:{status:'active'},
    requestRetry:{mode:'normal',executor:'single inherited llm-retry'},dshTuiAuth:'disabled',
    backends:{claude:value.backends.claude,codex:value.backends.codex},orcaHooks:value.orcaHooks};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2),usage='node scripts/dsh-native-acceptance.mjs --run --tui ABSOLUTE_STARTUP_LOG';
  if(args.length===3&&args[0]==='--run'&&args[1]==='--tui'&&path.isAbsolute(args[2])){
    try{console.log(JSON.stringify(acceptNativeDshTui({log:args[2]})));}catch(error){console.error(error.message);process.exitCode=1;}
  }else{console.error(usage);process.exitCode=2;}
}

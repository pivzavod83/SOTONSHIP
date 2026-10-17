import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root=fileURLToPath(new URL(".",import.meta.url));
const requestedPort=Number(process.env.PORT||4173);
const firstPort=Number.isInteger(requestedPort)&&requestedPort>0&&requestedPort<65536?requestedPort:4173;
let port=firstPort;
const lastPort=Math.min(firstPort+20,65535);
const types={".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"text/javascript; charset=utf-8"};
const server=createServer(async(req,res)=>{try{const requested=req.url==="/"?"index.html":req.url.split("?")[0].slice(1);const safe=normalize(requested).replace(/^(\.\.[/\\])+/g,"");const body=await readFile(join(root,safe));res.writeHead(200,{"Content-Type":types[extname(safe)]||"application/octet-stream","Cache-Control":"no-store"});res.end(body)}catch{res.writeHead(404,{"Content-Type":"text/plain"});res.end("Not found")}});

server.on("listening",()=>console.log(`Sotonship comparison demo: http://127.0.0.1:${port}`));
server.on("error",error=>{
  if(error.code==="EADDRINUSE"&&port<lastPort){
    const occupiedPort=port;
    port+=1;
    console.warn(`Port ${occupiedPort} is already in use; trying ${port} instead...`);
    setTimeout(()=>server.listen(port,"127.0.0.1"),25);
    return;
  }
  console.error(`Unable to start the demo server: ${error.message}`);
  process.exitCode=1;
});

server.listen(port,"127.0.0.1");

// Generate app/src/renderer/src/types/report.ts from the backend JSON
// schema. Never hand-edit the generated file.
import { compile } from 'json-schema-to-typescript'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const schemaPath = path.resolve(
  appDir,
  '../backend/schema/report.schema.json'
)
const outPath = path.join(appDir, 'src/renderer/src/types/report.ts')

const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'))
const ts = await compile(schema, 'Report', {
  bannerComment:
    '/* GENERATED from backend/schema/report.schema.json — do not edit; run npm run gen:types */',
  additionalProperties: false,
  strictIndexSignatures: true,
})
fs.mkdirSync(path.dirname(outPath), { recursive: true })
fs.writeFileSync(outPath, ts)
console.log(`wrote ${outPath}`)

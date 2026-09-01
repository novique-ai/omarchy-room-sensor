const fs = require("fs")
const path = require("path")
const vm = require("vm")
const assert = require("assert")

const ROOT = path.dirname(__dirname)

function load(relativePath) {
  const file = path.join(ROOT, relativePath)
  const raw = fs.readFileSync(file, "utf8")
  const context = {}
  vm.createContext(context)
  const source = raw.replace(/^\.pragma library\s*$/m, "")
  vm.runInContext(source, context)
  return context
}

function plain(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function deepEqual(actual, expected, message) {
  assert.deepStrictEqual(plain(actual), plain(expected), message)
}

module.exports = { load, ROOT, plain, deepEqual }

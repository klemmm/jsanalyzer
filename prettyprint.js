#!/usr/bin/env node
"use strict";

const escodegen = require('escodegen');
const process = require('process');
const fs = require('fs');

if (process.argv[3] === undefined) {
	console.log(`Usage: ${process.argv[0]} ${process.argv[1]} <input JSON file> <JS output file>`);
} else {

	try {
		console.log("Reading input file...");
		const data = fs.readFileSync(process.argv[2]);
		console.log("Parsing JSON...");
		const json = JSON.parse(data);
		console.log("Generating JS...");
		const js = escodegen.generate(json, {comment: true}) + "\n";
		console.log("Writing to output file...");
		fs.writeFileSync(process.argv[3], js);
		console.log("All done!");
	} catch (err) {
		console.log("" + err);
	}
}

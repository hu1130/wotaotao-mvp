const fs = require('fs');
const path = require('path');

for (const fileName of ['speech-showcase.js', 'speech-showcase.css']) {
    const filePath = path.join(__dirname, '..', fileName);
    const content = fs.readFileSync(filePath, 'utf8');
    fs.writeFileSync(filePath, content.replace(/ +\t/g, '\t').replace(/[ \t]+$/gm, ''), 'utf8');
}

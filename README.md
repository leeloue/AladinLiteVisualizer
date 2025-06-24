Aladin Lite Web Visualiser

An astronomical HiPS visualizer in the browser

Aladin Lite Web Visualiser is a website wich enables FITS convertion in HiPS, and HiPS visualization from the browser. It is developped at CDS, Strasbourg astronomical data center.

See A&A 578, A114 (2015) and IVOA HiPS Recommendation for more details about the HiPS standard.

More details on Aladin Lite documentation page. A new API technical documentation is now available.


Aladin Lite is available at this link.  
Aladin Lite web Visualizer is available at this link.



à quoi ça sert, comment est ce qu'on lance, et comment est ce que le code est organisé (répertoires)




Releases

A release page keeps track of all the current and previous builds. A release and beta versions, regularly updated are available. The beta version is usually more advanced than the release one but features more error prone and not production-ready code.


There is a new API documentation available here. Editable examples showing the API can also be found here.
Embed it into your projects

Terms of use: you are welcome to integrate Aladin Lite in your web pages and to customize its GUI to your needs, but please leave the Aladin logo and link intact at the bottom right of the view.

You can embed Aladin Lite it into your webpages in two ways
The vanilla way

Please include the javascript script of Aladin Lite v3 into your project. API differences from the v2 are minimal, here is a snippet of code you can use to embed it into your webpages:

<!doctype html>
<html>
<head>
    <!-- Mandatory when setting up Aladin Lite v3 for a smartphones/tablet usage -->
    <meta name="viewport" content="width=device-width, height=device-height, initial-scale=1.0, user-scalable=no">
</head>
<body>

<div id="aladin-lite-div" style="width: 500px; height: 400px"></div>
<script type="text/javascript" src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js" charset="utf-8"></script>

<script type="text/javascript">
    let aladin;
    A.init.then(() => {
        aladin = A.aladin('#aladin-lite-div', {fov: 360, projection: "AIT", cooFrame: 'equatorial', showCooGridControl: true, showSimbadPointerControl: true, showCooGrid: true});
    });
</script>

</body>
</html>

NPM deployment

A NPM package is deployed and maintained. It is used by ipyaladin, a jupyter widget allowing to run aladin lite in a notebook.

npm i aladin-lite

Aladin Lite can be imported with:

<script type="module">
    import A from 'aladin-lite';
    // your code...
</script>

New features

    Rust/WebGL2 new rendering engine
    Remove jQuery dep
    UI dev, better support for smartphones
    FITS images support
    WCS parsing, displaying an (JPEG/PNG) image in aladin lite view
    Display customized shapes (e.g. proper motions) from astronomical catalog data
    AVM tags parsing support
    Easy sharing of current « view »
    All VOTable serializations
    FITS tables
    Creating HiPS instance from an URL
    Local HiPS loading
    Multiple mirrors handling for HiPS tile retrival
    HiPS cube

Licence

Aladin Lite is currently licensed under GPL v3.0

If you think this license might prevent you from using Aladin Lite in your pages/application/portal, please open an issue or contact us
Contribution guidelines

There are several ways to contribute to Aladin Lite:

    report a bug: anyone is welcome to open an issue to report a bug. Please make sure first the issue does not exist yet. Be as specific as possible, and provide if possible detailed instructions about how to reproduce the problem.

    suggest a new feature: if you feel something is missing, check first if a similar feature request has not already been submitted in the open issues. If not, open a new issue, and give a detailed explanation of the feature you wish.

    develop new features/provide code fixing bugs. As open development is a new thing for us, we will in a first time only take into consideration code contribution (i.e. Pull Requests) from our close partners. In any case, please get in touch before starting a major update or rewrite.

Building steps

First you need to install the dependencies from the package.json Please run:

npm install

After that you are supposed to have the Rust toolchain installed to compile the core project into WebAssembly. Follow the steps from the Rust official website here You will also need wasm-pack, a tool helping compiling rust into a proper .wasm file.

Then you can build the project:

npm run build

Warning

If you are experimenting Rust compiling issues:

    Make sure you have your wasm-pack version updated. To do so:

cargo install wasm-pack --version ~0.12

    Remove your src/core/Cargo.lock file and src/core/target directory -- this ensures that you'd escape any bad compilation state:

git clean -di

    Then recompile

npm run build

It will generate the aladin lite compiled code into a dist/ directory located at the root of the repository. This directory contains two javascript files. aladin.umd.cjs follows the UMD module export convention and it is the one you need to use for your project.
Testing guidelines
Run the examples

A bunch of examples are located into the examples directory. To run them, start a localhost server:

npm run serve

Rust tests

These can be executed separately from the JS part:

    Compile the Rust code:

cd src/core
cargo check --features webgl2

    Run the tests:

cargo test --features webgl2

Snapshot comparisons

We use playwright for snapshot comparison testing. Only ground truth snapshots have been generated for MacOS/Darwin architecture. First install playwright:

npx playwright install

Run the tests, advises are given for opening the UI mode or for generating your own ground truth snapshots.

npm run test:playwright
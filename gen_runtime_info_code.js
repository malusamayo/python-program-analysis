"use strict";
var py = require("../python-program-analysis");
var fs = require('fs');
const { printNode, RefSet } = require("../python-program-analysis");
const { matchesProperty, map } = require("lodash");
const { printArg } = require("./dist/es5/printNode");
const { ADDRCONFIG } = require("dns");
let args = process.argv.slice(2);
let path = args[0];
//const path = './python-examples/python/';
let filename = path.split('\\').pop().split('/').pop();
let filename_no_suffix = filename.substring(0, filename.lastIndexOf('.'));
let suffix = filename.substring(filename.lastIndexOf('.'));
let dir = path.replace(filename, '');
let text = fs.readFileSync(path).toString();
let lineToCell = new Map();
let ins = new Map();
let outs = new Map();
let replace_strs = [];
let HEAD_STR =
    "import os\n" +
    "import pickle\n" +
    "import copy\n" +
    "import inspect, collections, functools\n" +
    "store_vars = []\n" +
    "my_labels = []\n" +
    "funcs = collections.defaultdict(lambda: collections.defaultdict(list))\n" +
    "my_dir_path = os.path.dirname(os.path.realpath(__file__))\n" +
    "ignore_types = [\"<class 'module'>\", \"<class 'type'>\"]\n" +
    "copy_types = [\n" +
    "    \"<class 'folium.plugins.marker_cluster.MarkerCluster'>\",\n" +
    "    \"<class 'matplotlib.axes._subplots.AxesSubplot'>\"\n" +
    "]\n" +
    "def my_store_info(info, var):\n" +
    "    if str(type(var)) in ignore_types:\n" +
    "        return\n" +
    "    my_labels.append(info)\n" +
    "    if str(type(var)) in copy_types:\n" +
    "        store_vars.append(copy.copy(var))\n" +
    "    else:\n" +
    "        store_vars.append(copy.deepcopy(var))\n" +
    "def func_info_saver(line):\n" +
    "    def inner_decorator(func):\n" +
    "        @functools.wraps(func)\n" +
    "        def wrapper(* args, ** kwargs):\n" +
    "            name = func.__name__ + \"_\" + str(line)\n" +
    "            args_name = tuple(inspect.signature(func).parameters)\n" +
    "            arg_dict = dict(zip(args_name, args))\n" +
    "            arg_dict.update(kwargs)\n" +
    "            funcs[name][\"loc\"] = line\n" +
    "            if len(funcs[name][\"args\"]) < 5:\n" +
    "                funcs[name][\"args\"].append(copy.deepcopy(arg_dict))\n" +
    "            rets = func(*args, **kwargs)\n" +
    "            if len(funcs[name][\"rets\"]) < 5:\n" +
    "                funcs[name][\"rets\"].append(copy.deepcopy([rets]))\n" +
    "            return rets\n" +
    "        return wrapper\n" +
    "    return inner_decorator\n";

let write_str =
    "store_vars.append(my_labels)\n" +
    "store_vars.append(dict(funcs))\n" +
    "f = open(os.path.join(my_dir_path, \"" + filename_no_suffix +
    "_log.dat\"), \"wb\")\n" +
    "pickle.dump(store_vars, f)\n" +
    "f.close()\n";

function init_lineToCell() {
    let lines = text.split("\n");
    let max_line = lines.length;
    let cur_cell = 0;
    for (let i = 0; i < max_line; i++) {
        if (lines[i].startsWith('# In['))
            cur_cell++;
        if (lines[i].startsWith("#"))
            continue;
        lineToCell.set(i + 1, cur_cell);
    }
    // console.log(lines);
}

function add(map, key, value) {
    if (map.get(key) == undefined)
        map.set(key, []);
    if (map.get(key).find(x => x == value) == undefined)
        map.get(key).push(value);
}

// add vars from external input or used for plotting 
function add_extra_vars(tree) {
    for (let stmt of tree.code) {
        // if (stmt.type == "assign") {
        //     // external input: x = pd.read_csv()
        //     for (let [i, src] of stmt.sources.entries()) {
        //         if (src.type == "call" && src.func.name == "read_csv") {
        //             add(ins, lineToCell.get(stmt.location.first_line), stmt.targets[i].id)
        //         }
        //     }
        // }

        // add plotting vars
        if (stmt.type == "call") {
            if (stmt.func.name == "plot") {
                let cell = lineToCell.get(stmt.location.first_line);
                if (stmt.func.value.type == "index")
                    add(outs, cell, stmt.func.value.value.id);
                else if (stmt.func.value.id == "plt") {
                    add(outs, cell, stmt.args[0].actual.id);
                    add(outs, cell, stmt.args[1].actual.id);
                } else
                    add(outs, cell, stmt.func.value.id);
            }
            if (["factorplot", "countplot", "barplot"].includes(stmt.func.name)) {
                for (let arg of stmt.args) {
                    if ("keyword" in arg && arg.keyword.id == "data") {
                        add(outs, lineToCell.get(stmt.location.first_line), arg.actual.id);
                    }
                }
            }
        }
    }
}

function contain_type(node, type) {
    if (node == undefined)
        return undefined;
    if (node.type == type)
        return printNode(node);
    if (node.targets != undefined) {
        for (let des of node.targets) {
            let res = contain_type(des, type);
            if (res != undefined)
                return res;
        }
    }
    if (node.sources != undefined) {
        for (let src of node.sources) {
            let res = contain_type(src, type);
            if (res != undefined)
                return res;
        }
    }
    if (node.args != undefined) {
        for (let arg of node.args) {
            let res = contain_type(arg.actual, type);
            if (res != undefined)
                return res;
        }
    }
    return undefined;
}

function static_analyzer(tree) {
    let static_comments = new Map();
    for (let [i, stmt] of tree.code.entries()) {
        // console.log(printNode(stmt));
        let lambda = contain_type(stmt, "lambda");
        if (lambda != undefined) {
            let lambda_rep = "func_info_saver(" + stmt.location.first_line + ")(" + lambda + ")";
            let stmt_str = printNode(stmt);
            stmt_str = stmt_str.replace(lambda, lambda_rep);
            replace_strs.push([stmt.location.first_line, stmt.location.last_line, stmt_str]);
        }
        if (stmt.type == "assign") {
            // external input: x = pd.read_csv()
            for (let [i, src] of stmt.sources.entries()) {
                // x[y] = x1[y1].map(...) || x.y = x1.y1.map(...)
                if (src.type == "call" && src.func.name == "map") {
                    let value_type = ["index", "dot"]
                    if (value_type.includes(stmt.targets[i].type)
                        && value_type.includes(src.func.value.type))
                        static_comments.set(stmt.location.first_line,
                            "add/change columns based on existing columns");
                    // same/different literal
                }
                // x = pd.get_dymmies()
                if (src.type == "call" && src.func.name == "get_dummies") {
                    static_comments.set(stmt.location.first_line,
                        "encoding in dummy variables");
                }
                // x1, x2, y1, y2 = train_test_split()
                if (src.type == "call" && src.func.name == "train_test_split") {
                    static_comments.set(stmt.location.first_line,
                        "spliting data to train set and test set");
                }
                // x = df.select_dtypes().columns
                if (src.type == "dot" && src.name == "columns") {
                    if (src.value.type == "call" && src.value.func.name == "select_dtypes")
                        static_comments.set(stmt.location.first_line,
                            "select columns of specific data types");
                }
                // x.at[] = ... || x.loc[] = ...
                if (stmt.targets[i].type == "index"
                    && ["at", "loc"].includes(stmt.targets[i].value.name)) {
                    static_comments.set(stmt.location.first_line,
                        "re-write the column");
                }
            }
        } else if (stmt.type == "call") {
            // x.fillna()
            if (stmt.func.name == "fillna") {
                static_comments.set(stmt.location.first_line,
                    "fill missing values");
            }
        }
    }
    console.log(static_comments)
    return static_comments;
}

function compute_flow_vars(code) {
    let tree = py.parse(code);
    // console.log(py.walk(tree).map(function (node) { return node.type; }));
    let cfg = new py.ControlFlowGraph(tree);
    // console.log(cfg.blocks);
    const analyzer = new py.DataflowAnalyzer();
    const flows = analyzer.analyze(cfg).dataflows;
    let line_in = new Map();
    let line_out = new Map();
    for (let flow of flows.items) {
        let fromLine = flow.fromNode.location.first_line;
        let toLine = flow.toNode.location.first_line;
        // use interSec to avoid missing in/out var bugs
        let defs = analyzer.getDefs(flow.fromNode, new RefSet()).items.map(x => x.name);
        let uses = analyzer.getUses(flow.toNode).items.map(x => x.name);
        let interSec = defs.filter(x => uses.includes(x));

        interSec.forEach(x => {
            add(line_in, toLine, x);
            add(line_out, fromLine, x);
        })
        // add in/out vars to cells
        if (flow.fromRef !== undefined) {
            // console.log(fromLine + "->" + toLine + " " + flow.fromNode.type + " " + flow.toNode.type + " " + flow.fromRef.name);
            add(line_in, toLine, flow.toRef.name);
            add(line_out, fromLine, flow.fromRef.name);
        }

        if (lineToCell.get(fromLine) < lineToCell.get(toLine)) {
            // console.log(fromLine + "->" + toLine + " " + flow.fromNode.type + " " + flow.toNode.type + " " + flow.toRef.name);
            // ignore import and funtion def
            if (["import", "def", "from"].includes(flow.fromNode.type))
                continue;
            interSec.forEach(x => {
                add(ins, lineToCell.get(toLine), x);
                add(outs, lineToCell.get(fromLine), x);
            })
            // console.log(analyzer.getUses(flow.toNode));
            add(ins, lineToCell.get(toLine), flow.toRef.name);
            add(outs, lineToCell.get(fromLine), flow.fromRef.name);
        }
        // console.log(flow.fromRef.name + "--------------" + flow.toRef.name)
        // console.log(py.printNode(flow.fromNode) +
        //     "\n -----------------> \n" + py.printNode(flow.toNode) + "\n");
    }
    add_extra_vars(tree);
    let comments = static_analyzer(tree);
    console.log(ins);
    console.log(outs);
    console.log(comments)
}

// type 1 == OUT, type 0 == IN
function print_info(cell, v, type) {
    return "my_store_info((" + cell + ", " + type + ", \"" + v + "\"), " + v + ")\n";
}

function insert_print_stmt(code) {
    let lines = code.split("\n");
    let max_line = lines.length;
    let cur_cell = 0;
    lines[0] = lines[0] + HEAD_STR;
    for (let item of replace_strs) {
        lines[item[0] - 1] = item[2];
        for (let i = item[0]; i < item[1]; i++)
            lines[i] = ""
    }
    for (let i = 0; i < max_line; i++) {
        if (lines[i].startsWith('# In[')) {
            if (outs.get(cur_cell) !== undefined)
                outs.get(cur_cell).forEach(x => lines[i - 1] += print_info(cur_cell, x, 1));
            cur_cell++;
            if (ins.get(cur_cell) !== undefined)
                ins.get(cur_cell).forEach(x => lines[i] += print_info(cur_cell, x, 0));
        }
        if (lines[i].startsWith("#"))
            continue;
        // deal with corner case
        if (lines[i].startsWith("get_ipython"))
            lines[i] = "";
        if (lines[i].startsWith("from __future__")) {
            lines[0] = lines[i] + lines[0];
            lines[i] = "";
        }
        let space = " ".repeat((lines[i].length - lines[i].trimLeft().length))
        if (lines[i].trim().startsWith("def")) {
            lines[i] = space + "@func_info_saver(" + (i + 1) + ")\n" + lines[i]
        }
        // deal with functions
        // let space = " ".repeat((lines[i].length - lines[i].trimLeft().length))
        // if (lines[i].trim().startsWith("def")) {
        //     func_name = lines[i].trim().substring(4, lines[i].lastIndexOf('('));
        //     lines[i] += space + "    " + "funcs[\"" + func_name + "\"] = {}\n";
        //     lines[i] += space + "    " + "funcs[\"" + func_name + "\"][\"cell\"] = " + cur_cell + "\n";
        //     lines[i] += space + "    " + "funcs[\"" + func_name + "\"][\"args\"] = copy.deepcopy(locals())\n";
        // }
        // if (lines[i].trim().startsWith("return")) {
        //     let rets = lines[i].trim().substring(7);
        //     lines[i] = space + "funcs[\"" + func_name + "\"][\"rets\"] = copy.deepcopy([" + rets + "])\n" + lines[i]
        // }
    }
    lines[max_line - 1] += write_str;
    return lines.join("\n");
}

init_lineToCell();
compute_flow_vars(text);
let modified_text = insert_print_stmt(text);
fs.writeFileSync(dir + filename_no_suffix + "_m" + suffix, modified_text);
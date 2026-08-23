/**
 * form_questions.csv から Google フォームを生成するスクリプト
 *
 * 【準備】
 * 1. CSV の ## 部分を実際の値に置き換えてから保存
 * 2. form_questions.csv を Google Drive（マイドライブ直下）にアップロード
 * 3. form_questions.csv を […] - [アプリで開く] - [Googleスプレッドシート]で開く
 * 4. [拡張機能] - [Apps Script] でプロジェクトを開く
 * 5. 以下の内容をこのcreate_forms.gs の内容にそのまま置き換え
 *    function myFunction() {
 *      
 *    }
 * 6. 実行をクリック
 * 7. 権限を承認して実行
 *
 * 【CSV 仕様】
 * form_questions.csv: 1行1エントリ
 *   - section_id   : config 行ではキー名、page_break では分岐先 ID
 *   - type         : config | text | paragraph | radio | checkbox | page_break
 *   - title        : config 行では設定値、それ以外は質問タイトル
 *   - required     : TRUE | FALSE
 *   - help_text    : 説明文（改行は \n と記述）
 *   - choices      : 選択肢をパイプ (|) 区切りで記述
 *   - other_option : TRUE で「その他（自由記述）」を追加
 *   - validation   : max_length:N  または  pattern:正規表現
 *   - branching    : 選択肢->移動先 をパイプ区切り
 *                    移動先: section_id | SUBMIT | NEXT
 *
 * 【注意】
 * Q15「要旨ファイルの提出」は GAS で作成不可のため、スクリプト実行後に
 * Google Forms 編集画面から手動でファイルアップロード質問を追加してください。
 * 追加場所: Q14「一般講演」の直後（セクション3の先頭）
 */

var QUESTIONS_FILE = 'form_questions.csv';

// ============================================================
// メイン関数
// ============================================================
function createVSJFormFromCSV() {
  var data      = loadData(QUESTIONS_FILE);
  buildForm(data.config, data.questions);
}

// ============================================================
// CSV 読み込み
// ============================================================
function getFileContent(filename) {
  var files = DriveApp.getFilesByName(filename);
  if (!files.hasNext()) throw new Error('ファイルが見つかりません: ' + filename);
  return files.next().getBlob().getDataAsString('UTF-8');
}

function loadData(filename) {
  var rows    = Utilities.parseCsv(getFileContent(filename));
  var headers = rows[0].map(function(h) { return h.trim(); });
  var config  = {};
  var questions = [];
  for (var i = 1; i < rows.length; i++) {
    var row     = rows[i];
    var isEmpty = !row.some(function(cell) { return cell.trim(); });
    if (isEmpty) continue;
    var obj = {};
    headers.forEach(function(h, j) { obj[h] = (row[j] || '').trim(); });
    if (obj['type'].toLowerCase() === 'config') {
      config[obj['section_id']] = obj['title'];
    } else {
      questions.push(obj);
    }
  }
  return {config: config, questions: questions};
}

// ============================================================
// フォーム構築
// ============================================================
function buildForm(config, questions) {
  var form = FormApp.create(config['title'] || '無題');
  if (config['description']) {
    form.setDescription(config['description'].replace(/\\n/g, '\n'));
  }
  form.setCollectEmail(false);

  var sectionMap  = {};  // section_id → PageBreakItem
  var branchQueue = [];  // 分岐は全アイテム作成後に処理

  questions.forEach(function(q) {
    var type       = (q['type']         || '').toLowerCase();
    var title      = q['title']         || '';
    var required   = (q['required']     || '').toUpperCase() === 'TRUE';
    var helpText   = (q['help_text']    || '').replace(/\\n/g, '\n');
    var choicesStr = q['choices']       || '';
    var otherOpt   = (q['other_option'] || '').toUpperCase() === 'TRUE';
    var validation = q['validation']    || '';
    var branching  = q['branching']     || '';
    var sectionId  = q['section_id']    || '';
    var choices    = choicesStr ? choicesStr.split('|') : [];

    switch (type) {
      case 'page_break':
        var pb = form.addPageBreakItem().setTitle(title);
        if (sectionId) sectionMap[sectionId] = pb;
        break;

      case 'text':
        var ti = form.addTextItem().setTitle(title).setRequired(required);
        if (helpText)   ti.setHelpText(helpText);
        if (validation) applyTextValidation(ti, validation, helpText);
        break;

      case 'paragraph':
        var pi = form.addParagraphTextItem().setTitle(title).setRequired(required);
        if (helpText)   pi.setHelpText(helpText);
        if (validation) applyParagraphValidation(pi, validation);
        break;

      case 'radio':
        var ri = form.addMultipleChoiceItem().setTitle(title).setRequired(required);
        if (helpText) ri.setHelpText(helpText);
        if (branching) {
          branchQueue.push({item: ri, branching: branching});
        } else if (choices.length > 0) {
          ri.setChoiceValues(choices);
        }
        if (otherOpt) ri.showOtherOption(true);
        break;

      case 'checkbox':
        var ci = form.addCheckboxItem().setTitle(title).setRequired(required);
        if (helpText)        ci.setHelpText(helpText);
        if (choices.length)  ci.setChoiceValues(choices);
        if (otherOpt)        ci.showOtherOption(true);
        break;

      default:
        Logger.log('スキップ: type=' + type + (title ? ' / ' + title : ''));
    }
  });

  // 分岐設定（全アイテム作成後）
  branchQueue.forEach(function(entry) {
    var mcItem     = entry.item;
    var choiceObjs = entry.branching.split('|').map(function(rule) {
      var arrowIdx = rule.indexOf('->');
      var val  = rule.substring(0, arrowIdx).trim();
      var dest = rule.substring(arrowIdx + 2).trim();
      if (dest === 'SUBMIT') {
        return mcItem.createChoice(val, FormApp.PageNavigationType.SUBMIT);
      } else if (dest === 'NEXT' || dest === '') {
        return mcItem.createChoice(val, FormApp.PageNavigationType.CONTINUE);
      } else if (sectionMap[dest]) {
        return mcItem.createChoice(val, sectionMap[dest]);
      } else {
        Logger.log('警告: 分岐先が見つかりません: ' + dest);
        return mcItem.createChoice(val);
      }
    });
    mcItem.setChoices(choiceObjs);
  });

  Logger.log('フォームを作成しました');
  Logger.log('編集URL\n' + form.getEditUrl());
  Logger.log('回答URL\n' + form.getPublishedUrl());
}

// ============================================================
// バリデーション設定
// ============================================================
function applyTextValidation(item, validation, helpText) {
  var colonIdx = validation.indexOf(':');
  var rule     = validation.substring(0, colonIdx);
  var value    = validation.substring(colonIdx + 1);
  var builder  = FormApp.createTextValidation();
  if (rule === 'max_length') {
    builder.requireTextLengthLessThanOrEqualTo(parseInt(value));
  } else if (rule === 'pattern') {
    builder.requireTextMatchesPattern(value);
    if (helpText) builder.setHelpText(helpText);
  }
  item.setValidation(builder.build());
}

function applyParagraphValidation(item, validation) {
  var colonIdx = validation.indexOf(':');
  var rule     = validation.substring(0, colonIdx);
  var value    = validation.substring(colonIdx + 1);
  var builder  = FormApp.createParagraphTextValidation();
  if (rule === 'max_length') {
    builder.requireTextLengthLessThanOrEqualTo(parseInt(value));
  }
  item.setValidation(builder.build());
}

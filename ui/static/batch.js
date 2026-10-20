// Batch review page: "Approve all in this sample" fills every pair's verdict with Approve so a
// reviewer who has gone through the sample only has to flip the exceptions to Reject. The form still
// posts one explicit verdict per pair, and the server still requires exactly the sampled pairs.
(function () {
  "use strict";
  var button = document.getElementById("approve-all");
  var status = document.getElementById("verdict-status");
  var form = button && button.form;
  if (!form) return;

  function summarise() {
    var approved = form.querySelectorAll('input[type="radio"][value="APPROVE"]:checked').length;
    var rejected = form.querySelectorAll('input[type="radio"][value="REJECT"]:checked').length;
    var total = form.querySelectorAll('input[type="radio"][value="APPROVE"]').length;
    status.textContent = approved + " approved, " + rejected + " rejected, " + (total - approved - rejected) + " undecided of " + total;
    status.classList.toggle("text-danger", rejected > 0);
  }

  button.addEventListener("click", function () {
    form.querySelectorAll('input[type="radio"][value="APPROVE"]').forEach(function (radio) {
      radio.checked = true;
    });
    summarise();
  });
  form.addEventListener("change", summarise);
  summarise();
})();

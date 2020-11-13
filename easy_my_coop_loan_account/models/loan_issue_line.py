# Copyright 2019 Coop IT Easy SCRL fs
#   Houssine BAKKALI <houssine@coopiteasy.be>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class LoanIssueLine(models.Model):
    _inherit = "loan.issue.line"

    awaiting_move_id = fields.Many2one(
        "account.move",
        string="Awaiting payment account move"
    )

    @api.multi
    def get_loan_move_line(self, move_id):
        self.ensure_one()
        move_line = {
            "partner_id": self.partner_id.id,
            "date_maturity": date.today(),
            "move_id": move_id,
        }
        return move_line

    @api.multi
    def create_waiting_payment_moves(self):
        move_obj = self.env["account.move"]
        move_line_obj = self.env["account.move.line"]
        for line in self:
            company = line.company_id
            move_vals = {
                "ref": line.reference,
                "date": date.today(),
                "journal_id": company.awaiting_loan_payment_journal.id,
            }
            move = move_obj.create(move_vals)
            loan_vals = line.get_loan_move_line(move.id)
            loaner_vals = line.get_loan_move_line(move.id)

            loan_vals["account_id"] = company.debt_long_term_account.id
            loan_vals["credit"] = line.amount

            loaner_vals["account_id"] = company.awaiting_loan_payment_account.id
            loaner_vals["debit"] = line.amount

            move_line_obj.create([loan_vals, loaner_vals])
            line.awaiting_move_id = move

    @api.multi
    def action_request_payment(self):
        self.create_waiting_payment_moves()
        super(LoanIssueLine, self).action_request_payment()

    @api.multi
    def action_paid(self):
        paid_by = self.env.context.get("paid_by_bank_statement")
        if paid_by:
            super(LoanIssueLine, self).action_paid()
        else:
            raise UserError(_("The payment must be registered"
                              " by bank statement"))
# Copyright 2019 Coop IT Easy SCRL fs
#   Houssine BAKKALI <houssine@coopiteasy.be>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import calendar
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class LoanIssueLine(models.Model):
    _name = "loan.issue.line"
    _description = "Loan Issue Line"
    _order = "date desc, id"

    @api.multi
    @api.depends("quantity", "face_value")
    def _compute_amount(self):
        for line in self:
            line.amount = line.face_value * line.quantity

    reference = fields.Char(
        string="Reference",
        copy=False,
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    loan_issue_id = fields.Many2one(
        "loan.issue", string="Loan issue", required=True
    )
    interest_lines = fields.One2many(
        "loan.interest.line", "issue_line", string="Interest lines"
    )
    quantity = fields.Integer(string="quantity", required=True)
    face_value = fields.Monetary(
        related="loan_issue_id.face_value",
        currency_field="company_currency_id",
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Subscriber",
        required=True
    )
    date = fields.Date(
        string="Subscription date",
        default=lambda self: date.strftime(date.today(), "%Y-%m-%d"),
        required=True,
    )
    payment_date = fields.Date(
        string="Payment date")
    amount = fields.Monetary(
        string="Subscribed amount",
        currency_field="company_currency_id",
        compute="_compute_amount",
        store=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("subscribed", "Subscribed"),
            ("waiting", "Waiting payment"),
            ("paid", "paid"),
            ("cancelled", "Cancelled"),
            ("ended", "Ended"),
        ],
        string="State",
        required=True,
        default="draft",
    )
    company_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="loan_issue_id.company_id",
        string="Company",
        readonly=True,
    )

    def get_loan_sub_mail_template(self):
        return self.env.ref(
            "easy_my_coop_loan.loan_subscription_confirmation", False
        )

    def get_loan_pay_req_mail_template(self):
        return self.env.ref(
            "easy_my_coop_loan.loan_issue_payment_request", False
        )

    @api.model
    def create(self, vals):
        line = super(LoanIssueLine, self).create(vals)

        confirmation_mail_template = line.get_loan_sub_mail_template()
        confirmation_mail_template.send_mail(line.id)

        return line

    @api.multi
    def action_draft(self):
        for line in self:
            line.write({"state": "draft"})

    @api.multi
    def action_validate(self):
        for line in self:
            line.write({"state": "subscribed"})

    @api.multi
    def action_request_payment(self):
        pay_req_mail_template = self.get_loan_pay_req_mail_template()

        for line in self:
            pay_req_mail_template.send_mail(line.id)
            line.write({"state": "waiting"})

    @api.multi
    def action_cancel(self):
        for line in self:
            line.write({"state": "cancelled"})

    @api.multi
    def get_confirm_paid_email_template(self):
        self.ensure_one()
        return self.env.ref(
            "easy_my_coop_loan.email_template_loan_confirm_paid"
        )

    @api.multi
    def action_paid(self):
        loan_email_template = self.get_confirm_paid_email_template()
        for line in self:
            vals = {"state": "paid"}
            if not line.payment_date:
                vals["payment_date"] = fields.Date.today()
            line.write(vals)
            line.action_compute_interest()
            loan_email_template.sudo().send_mail(line.id, force_send=False)

    def get_number_of_days(self, year):
        if calendar.isleap(year):
            return 366
        else:
            return 365

    @api.multi
    def action_compute_interest(self):
        for line in self:
            loan_issue = line.loan_issue_id
            vals = {
                "issue_line": line.id,
                "taxes_rate": loan_issue.taxes_rate,
            }
            list_vals = []
            accrued_amount = self.amount
            accrued_interest = 0
            accrued_net_interest = 0
            accrued_taxes = 0
            taxes_amount = 0
            diff_days = 0

            # In case of a recompute is done. Only the interest lines
            # in the future will be deleted. We also needed to determine
            # from which year we'll have to regenerate the lines.
            # Through the beautiful mind of Houssine, we implemented
            # a small piece code to allows it.
            today = fields.Date.today()
            posted_lines = line.interest_lines.filtered(
                            lambda r: r.state == "paid" or
                            r.due_date < today)
            futur_lines = line.interest_lines - posted_lines
            start_to_line = len(posted_lines) + 1
            futur_lines.unlink()

            loan_term = int(loan_issue.loan_term / 12)

            # if payment_date is first day of the month
            # we take the current month
            if line.payment_date.day == 1:
                start_date = line.payment_date
            else:
                start_date = line.payment_date + relativedelta(months=+1,
                                                               day=1)

                # we calculate the number of day between payment date
                # and the end of the month of the payment
                diff_days = ((start_date - relativedelta(days=1)) -
                             line.payment_date).days

            rate = loan_issue.rate / 100

            # take leap year into account
            days = self.get_number_of_days(line.payment_date.year)
            interim_amount = line.amount * rate * (diff_days / days)

            due_date = start_date + relativedelta(years=+loan_term)

            for year in range(1, loan_term + 1):
                interest = accrued_amount * rate
                due_amount = 0
                if loan_issue.capital_payment == "end":
                    if year == loan_term:
                        due_amount = line.amount
                else:
                    due_amount = line.amount * (loan_term / 100)
                    accrued_amount -= due_amount

                if loan_issue.interest_payment == "end":
                    accrued_interest += interest
                    accrued_amount += interest
                    net_interest = 0
                    if year == loan_term:
                        taxes_amount = (accrued_interest *
                                        (loan_issue.taxes_rate / 100)
                                        )
                        net_interest = accrued_interest - taxes_amount
                        due_amount += net_interest
                else:
                    due_date = start_date + relativedelta(years=+year)
                    taxes_amount = interest * (loan_issue.taxes_rate / 100)
                    net_interest = interest - taxes_amount
                    due_amount += net_interest
                    accrued_interest = interest

                if year == 1:
                    interest += interim_amount
                    accrued_interest = interest

                accrued_net_interest += net_interest
                accrued_taxes += taxes_amount
                vals["due_date"] = due_date
                vals["due_amount"] = due_amount
                vals["interest"] = interest
                vals["net_interest"] = net_interest
                vals["taxes_amount"] = taxes_amount
                vals["accrued_amount"] = accrued_amount
                vals["accrued_interest"] = accrued_interest
                vals["accrued_net_interest"] = accrued_net_interest
                vals["accrued_taxes"] = accrued_taxes
                vals["name"] = year
                if year >= start_to_line:
                    list_vals.append(vals.copy())

            self.env["loan.interest.line"].create(list_vals)

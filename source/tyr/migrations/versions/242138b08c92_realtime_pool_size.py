"""
    Settings for parallel calls to real-time proxies : realtime_pool_size
    - defines the number of greenlets to use

Revision ID: 242138b08c92
Revises: 3acdde6329db
Create Date: 2018-02-15 11:42:01.190624

"""

# revision identifiers, used by Alembic.
revision = '242138b08c92'
down_revision = '3acdde6329db'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('instance', sa.Column('realtime_pool_size', sa.Integer(), nullable=True))
    op.alter_column('instance', 'bss_provider',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default='true')
    op.alter_column('poi_type_json', 'poi_types_json',
               existing_type=sa.TEXT(),
               nullable=True)
    op.alter_column('user', 'billing_plan_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.alter_column('user', 'end_point_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('user', 'end_point_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('user', 'billing_plan_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('poi_type_json', 'poi_types_json',
               existing_type=sa.TEXT(),
               nullable=False)
    op.alter_column('instance', 'bss_provider',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default='true')
    op.drop_column('instance', 'realtime_pool_size')
    ### end Alembic commands ###
